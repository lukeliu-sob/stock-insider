#!/usr/bin/env python3
"""Change-set gate: governance parity (pi-adaptation.md §4).

A change set that touches the permission model or either harness's
governance files must also touch docs/code-governance/pi-adaptation.md
in the same change set — updating one harness and not the other is a
defect.

Environment: CI_BASE_SHA. Without it the gate skips (local mode).
"""

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TRIGGER_PREFIXES = (
    "docs/architecture/permission-model.md",
    ".opencode/",
    ".pi/",
)
PARITY_DOC = "docs/code-governance/pi-adaptation.md"


def changed_files():
    base = os.environ.get("CI_BASE_SHA")
    if not base:
        return None
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def main() -> None:
    changed = changed_files()
    if changed is None:
        print("PASS parity gate: no CI_BASE_SHA (local mode, skipped)")
        return
    if not changed:
        print("PASS parity gate: no changes")
        return

    triggers = [f for f in changed if f.startswith(TRIGGER_PREFIXES)]
    if triggers and PARITY_DOC not in changed:
        sys.exit(
            f"FAIL parity gate: change set touches {triggers} "
            f"without updating {PARITY_DOC}"
        )
    print("PASS parity gate")


if __name__ == "__main__":
    main()
