#!/usr/bin/env python3
"""Structural gate: trace-matrix coverage (verification rule R1).

The set of requirement IDs in docs/architecture/trace-matrix.md must
equal the registry entry set exactly, per-ID. Combined rows
("PERF-001/002/003") fail by construction (see BD-002).
Requires: pyyaml.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs" / "req" / "requirements.yaml"
MATRIX = ROOT / "docs" / "architecture" / "trace-matrix.md"


def main() -> None:
    import yaml

    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    expected = {r["id"].split("REQ-SI-", 1)[1] for r in registry["requirements"]}

    text = MATRIX.read_text(encoding="utf-8")
    found = set(re.findall(r"\b(?:FR|INV|QA|PERF|COST|GOV|SEC)-\d{3}\b", text))
    found |= {
        m.split("REQ-SI-", 1)[1] for m in re.findall(r"REQ-SI-[A-Z]+-\d{3}", text)
    }

    missing = sorted(expected - found)
    phantom = sorted(found - expected)
    if missing or phantom:
        sys.exit(f"FAIL trace coverage: missing={missing} phantom={phantom}")
    print(
        f"PASS trace coverage: {len(expected)}/{len(expected)} registry entries mapped"
    )


if __name__ == "__main__":
    main()
