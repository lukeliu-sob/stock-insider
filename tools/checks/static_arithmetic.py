"""Static arithmetic gate: market-data arithmetic lives in data/compute.

FR-006 acceptance (a) references this structural check; blueprint
S10 and risk-list R-05 describe it. Until 2026-09-29 it did not
exist - three documents and one approved test plan described a
control that had never been built, and no approval chain caught it
(third-party review finding 3). This is that control, built for
real: an AST scan that fails the build when arithmetic operators
act on market-data field identifiers anywhere outside
data/compute/.

The scan is deliberately conservative: it flags BinOp and augmented
assignment nodes (+ - * / // % **) and aggregation calls (sum,
statistics/numpy/pandas-style mean, std, diff, pct_change, ...) whose
operands reference market-field identifier roots
(close/open/high/low/adjusted_close/volume/...), directly, through a
key variable or default parameter, or through a one-level alias
(including a comprehension that yields a market field; TP-019).
Calls into compute functions are the sanctioned path and never
flagged; comparisons, selection (min/max) and string formatting are
out of scope. A value renamed through an unrelated parameter name
(def f(last_px, first_px)) is beyond a name-based gate - recorded as
a known limit.

Implements: REQ-SI-FR-006 (ADR-002; TP-016 PR-delta, TP-019)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MARKET_FIELDS = frozenset(
    {
        "close",
        "open",
        "high",
        "low",
        "adjusted_close",
        "adj_close",
        "prev_close",
        "last_close",
        "volume",
        "open_price",
        "close_price",
        "quote",
    }
)

ARITH_OPS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
)

COMPUTE_PREFIX = ("data", "compute")


#: Aggregations that ARE market-data arithmetic even without a BinOp
#: node (fifth audit, TP-019): sum(r["close"] for r in rows),
#: statistics.mean(...), series.pct_change(). min/max (selection),
#: round (display) and len (counting) are deliberately absent.
AGGREGATE_FUNCTIONS = frozenset({"sum", "fsum"})
AGGREGATE_ATTRS = frozenset(
    {
        "sum", "fsum", "mean", "fmean", "median", "stdev", "pstdev", "variance",
        "pvariance", "geometric_mean", "harmonic_mean", "std", "var", "diff",
        "cumsum", "cumprod", "prod", "average", "pct_change",
    }
)

_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp)


def _walk_expression(node: ast.AST):
    """ast.walk, minus f-string bodies: formatting a value is not arithmetic.

    A BinOp INSIDE an f-string is still visited by the module-level walk
    in scan(); only identifier collection for an enclosing expression
    stops at the f-string (line += f"... {row['volume']}" is display).
    """
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.JoinedStr):
            continue
        yield current
        stack.extend(ast.iter_child_nodes(current))


def _identifiers(node: ast.AST, market_keys: "set[str] | None" = None) -> set[str]:
    """Identifier roots referenced by an expression node.

    Fourth-audit N1 completion (TP-018b): recognizes row["close"],
    row.get("close") (dict-access calls with constant market-field
    keys), variables USED AS KEYS whose value is a market-field string
    (key = "close"; row[key]), and one-level aliases (c = row["close"]
    resolves through the caller-supplied alias set).
    """
    aliases = market_keys or set()
    out: set[str] = set()
    for sub in _walk_expression(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
        elif isinstance(sub, ast.Subscript):
            sl = sub.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                out.add(sl.value)
            elif isinstance(sl, ast.Name) and sl.id in aliases:
                out.add(sl.id)
        elif isinstance(sub, ast.Call):
            fn = sub.func
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr in ("get", "pop", "setdefault")
                and sub.args
            ):
                first = sub.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    out.add(first.value)
                elif isinstance(first, ast.Name) and first.id in aliases:
                    out.add(first.id)
    return out


def _scope_market_names(tree: ast.AST) -> "set[str]":
    """Names that carry a market-field string or a market-field value.

    One conservative pass over Assign targets: key = "close" makes key
    a market-KEY variable; c = row["close"] (or row.get("close")) makes
    c a market-value alias. Only direct assignments propagate (no
    chains through calls); anything more complex stays untracked and
    relies on the base identifier rules.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            names.update(_market_key_parameters(node.args))
            continue
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not targets:
            continue
        value = node.value
        # key = "close"
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value in MARKET_FIELDS:
            names.update(targets)
            continue
        # c = row["close"] / row.get("close") / row[key-with-market-value]
        # DIRECT data reads only: a value that is itself arithmetic
        # (a = row["close"] * 2) is already flagged at its own BinOp and
        # must not re-taint downstream uses (no double counting).
        if isinstance(value, (ast.Subscript, ast.Call)):
            idents = _identifiers(value)
            if idents & MARKET_FIELDS:
                names.update(targets)
            continue
        # closes = [r["close"] for r in rows] (TP-019): the produced
        # ELEMENT decides - a comprehension that merely filters on a
        # market field yields rows, not market values
        if isinstance(value, _COMPREHENSIONS) and _identifiers(value.elt) & MARKET_FIELDS:
            names.update(targets)
        elif isinstance(value, ast.DictComp) and _identifiers(value.value) & MARKET_FIELDS:
            names.update(targets)
    return names


def _market_key_parameters(args: ast.arguments) -> "set[str]":
    """Parameters whose DEFAULT is a market-field key (def f(row, k="close")).

    TP-019: a key passed through a default parameter used to escape the
    variable-key rule, which only tracked plain assignments.
    """
    names: set[str] = set()
    positional = [*args.posonlyargs, *args.args]
    for arg, default in zip(positional[len(positional) - len(args.defaults):], args.defaults):
        if isinstance(default, ast.Constant) and default.value in MARKET_FIELDS:
            names.add(arg.arg)
    for arg, kw_default in zip(args.kwonlyargs, args.kw_defaults):
        if isinstance(kw_default, ast.Constant) and kw_default.value in MARKET_FIELDS:
            names.add(arg.arg)
    return names


def _aggregate_hit(node: ast.Call, market_names: "set[str]") -> "set[str]":
    """Market identifiers fed into an aggregation call (sum, mean, pct_change ...)."""
    fn = node.func
    parts: list[ast.AST] = [*node.args, *(kw.value for kw in node.keywords)]
    if isinstance(fn, ast.Name) and fn.id in AGGREGATE_FUNCTIONS:
        pass
    elif isinstance(fn, ast.Attribute) and fn.attr in AGGREGATE_ATTRS:
        parts.append(fn.value)  # series["close"].mean(): the receiver is the data
    else:
        return set()
    idents: set[str] = set()
    for part in parts:
        idents |= _identifiers(part, market_names)
    return idents & (MARKET_FIELDS | market_names)


def _under_compute(rel_parts: tuple[str, ...]) -> bool:
    """True for modules inside data/compute (the sanctioned home)."""
    return tuple(rel_parts[:2]) == COMPUTE_PREFIX


def scan(root: Path) -> list[str]:
    """Return violation strings for market-data arithmetic outside compute."""
    violations: list[str] = []
    src = root / "src" / "stockinsider"
    if not src.exists():
        return violations
    for path in sorted(src.rglob("*.py")):
        rel_parts = path.relative_to(src).with_suffix("").parts
        if _under_compute(rel_parts):
            continue
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        market_names = _scope_market_names(tree)
        for node in ast.walk(tree):
            hit: set[str] = set()
            if isinstance(node, ast.BinOp) and isinstance(node.op, ARITH_OPS):
                idents = _identifiers(node.left, market_names) | _identifiers(node.right, market_names)
                hit = idents & (MARKET_FIELDS | market_names)
            elif isinstance(node, ast.AugAssign) and isinstance(node.op, ARITH_OPS):
                # total += r["close"] (TP-019): no BinOp node exists
                idents = _identifiers(node.target, market_names) | _identifiers(node.value, market_names)
                hit = idents & (MARKET_FIELDS | market_names)
            elif isinstance(node, ast.Call):
                hit = _aggregate_hit(node, market_names)
            if hit:
                violations.append(
                    f"{rel}:{node.lineno}: arithmetic on market field(s) "
                    f"{sorted(hit)} outside data/compute"
                )
    return violations


def main() -> None:
    """CI entry: fail the build on any violation."""
    root = Path(__file__).resolve().parents[2]
    violations = scan(root)
    if violations:
        print("FAIL static arithmetic gate (FR-006a):")
        for entry in violations:
            print(f"  {entry}")
        sys.exit(1)
    print("PASS static arithmetic gate: market-data arithmetic confined to data/compute")


if __name__ == "__main__":
    main()
