#!/usr/bin/env python3
"""Structural gate: docstring traceability (structural-constraints §4, rule R3).

Every Python module under src/ and every public function/class must
carry an "Implements: REQ-SI-..." line; referenced IDs must exist in
the registry. No-op (pass with note) until src/ lands — tracked as
debt DE-05. Requires: pyyaml.
"""

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
REQ_ID = re.compile(r"REQ-SI-(?:FR|INV|QA|PERF|COST|GOV|SEC)-\d{3}")


def main() -> None:
    py_files = sorted(SRC.rglob("*.py")) if SRC.exists() else []
    if not py_files:
        print("PASS docstring gate: no src/ targets yet [DE-05 guard]")
        return

    import yaml

    registry = yaml.safe_load(
        (ROOT / "docs" / "req" / "requirements.yaml").read_text(encoding="utf-8")
    )
    valid_ids = {r["id"] for r in registry["requirements"]}

    violations = []

    def check_doc(node, label):
        doc = ast.get_docstring(node)
        if not doc or "Implements:" not in doc:
            violations.append(f"{label}: missing 'Implements:' docstring")
            return
        unknown = [i for i in REQ_ID.findall(doc) if i not in valid_ids]
        if not REQ_ID.search(doc):
            violations.append(f"{label}: no requirement ID in docstring")
        if unknown:
            violations.append(f"{label}: unknown IDs {unknown}")

    for path in py_files:
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        check_doc(tree, f"{rel} (module)")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith("_"):
                    continue
                check_doc(node, f"{rel}::{node.name}")

    if violations:
        sys.exit("FAIL docstring gate:\n  " + "\n  ".join(violations[:30]))
    print(f"PASS docstring gate: {len(py_files)} files traced")


if __name__ == "__main__":
    main()
