"""Static arithmetic gate: market-data arithmetic lives in data/compute.

FR-006 acceptance (a) references this structural check; blueprint
S10 and risk-list R-05 describe it. Until 2026-09-29 it did not
exist - three documents and one approved test plan described a
control that had never been built, and no approval chain caught it
(third-party review finding 3). This is that control, built for
real: an AST scan that fails the build when arithmetic operators
act on market-data field identifiers anywhere outside
data/compute/.

The scan is deliberately conservative: it flags only BinOp nodes
(+ - * / // % **) whose operand expressions reference market-field
identifier roots (close/open/high/low/adjusted_close/volume/...).
Calls into compute functions are the sanctioned path and never
flagged; comparisons and string operations are out of scope.

Implements: REQ-SI-FR-006 (ADR-002; TP-016 PR-delta)
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


def _identifiers(node: ast.AST) -> set[str]:
    """Identifier roots referenced by an expression node."""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
        elif isinstance(sub, ast.Subscript):
            # row["close"] — the subscript literal names the field (N1)
            sl = sub.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                out.add(sl.value)
    return out


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
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ARITH_OPS):
                idents = _identifiers(node.left) | _identifiers(node.right)
                hit = idents & MARKET_FIELDS
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
