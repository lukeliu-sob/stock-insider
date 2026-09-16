#!/usr/bin/env python3
"""Change-set gate: test-plan approval (blocking gate D7-1, GOV-006).

A PR touching src/ or test/ must reference an approved test plan in its
body: "Test-Plan: TP-NNN", with docs/test-plans/TP-NNN.md present and
carrying an approved status. Approval preceding implementation is
reviewer-verified from file history (see GOV-006 tradeoff).

Environment: CI_BASE_SHA, PR_BODY. Without them the gate skips (local
mode / non-PR context).
"""

import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TRIGGER_PREFIXES = ("src/", "test/")
TP_REF = re.compile(r"Test-Plan:\s*(TP-\d{3})", re.IGNORECASE)
# Approved status: literal "status: approved" or the template's table
# row "| Status | approved |" (case-insensitive).
TP_APPROVED = re.compile(r"status:\s*approved|\|\s*status\s*\|\s*approved\s*\|", re.IGNORECASE)


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
    body = os.environ.get("PR_BODY")
    if changed is None or not body:
        print("PASS test-plan gate: non-PR context (skipped)")
        return

    triggers = [f for f in changed if f.startswith(TRIGGER_PREFIXES)]
    if not triggers:
        print("PASS test-plan gate: no implementation files touched")
        return

    match = TP_REF.search(body)
    if not match:
        sys.exit(f"FAIL test-plan gate: PR body lacks 'Test-Plan: TP-NNN' while touching {triggers} (GOV-006 / D7-1)")

    tp_id = match.group(1).upper()
    tp_file = ROOT / "docs" / "test-plans" / f"{tp_id}.md"
    if not tp_file.exists():
        sys.exit(f"FAIL test-plan gate: {tp_file} does not exist")
    if not TP_APPROVED.search(tp_file.read_text(encoding="utf-8")):
        sys.exit(f"FAIL test-plan gate: {tp_id} is not approved")
    print(f"PASS test-plan gate: {tp_id} referenced and approved")


if __name__ == "__main__":
    main()
