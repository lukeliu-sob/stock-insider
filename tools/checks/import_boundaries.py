#!/usr/bin/env python3
"""Structural gate: import boundaries (blueprint §5 dependency rules).

Forbidden edges (checked exactly; intra-package imports are allowed):
  data   -> agent
  agent  -> data        (exception: agent/registry may import data facade)
  any    -> cli
  shared -> any internal package

No-op (pass with note) until src/ lands — tracked as debt DE-05.
"""

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "stockinsider"


def tier_of_parts(parts):
    """parts is the import path below 'stockinsider', e.g. ['data','store']."""
    if not parts:
        return None
    top = parts[0]
    if top == "shared":
        return "shared"
    if top == "data":
        return "data"
    if top == "agent":
        return (
            "agent.registry"
            if len(parts) > 1 and parts[1].startswith("registry")
            else "agent"
        )
    if top == "cli":
        return "cli"
    return None


def file_tier(path: pathlib.Path):
    parts = path.relative_to(SRC).with_suffix("").parts
    return tier_of_parts(parts), list(parts)


def main() -> None:
    if not SRC.exists():
        print("PASS import boundaries: no src/ targets yet [DE-05 guard]")
        return

    violations = []
    for path in sorted(SRC.rglob("*.py")):
        src_tier, src_parts = file_tier(path)
        if src_tier is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    imports.append((node.module or "").split("."))
                else:
                    base = (
                        src_parts[: len(src_parts) - node.level]
                        if node.level
                        else src_parts
                    )
                    imports.append(
                        base + ((node.module or "").split(".") if node.module else [])
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split("."))

        for mod in imports:
            if len(mod) > 1 and mod[0] == "stockinsider":
                tgt = tier_of_parts(mod[1:])
                if tgt is None:
                    continue
                bad = (
                    (src_tier == "data" and tgt in ("agent", "agent.registry"))
                    or (src_tier == "agent" and tgt == "data")
                    or (tgt == "cli" and src_tier != "cli")
                    # shared may not depend on other internal packages,
                    # but intra-package imports are legitimate.
                    or (src_tier == "shared" and tgt is not None and tgt != "shared")
                )
                if bad:
                    violations.append(f"{rel}: {src_tier} -> {tgt} ({'.'.join(mod)})")

    if violations:
        sys.exit("FAIL import boundaries:\n  " + "\n  ".join(violations[:30]))
    print("PASS import boundaries")


if __name__ == "__main__":
    main()
