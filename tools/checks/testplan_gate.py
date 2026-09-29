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
TP_REF = re.compile(r"Test-Plan:\s*(TP-\d{3}[a-z]?)", re.IGNORECASE)
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

    raw_id = match.group(1)
    tp_id = raw_id[:2].upper() + raw_id[2:]  # normalize prefix only; suffix case is significant
    tp_file = ROOT / "docs" / "test-plans" / f"{tp_id}.md"
    if not tp_file.exists():
        sys.exit(f"FAIL test-plan gate: {tp_file} does not exist")
    tp_text = tp_file.read_text(encoding="utf-8")
    if not TP_APPROVED.search(tp_text):
        sys.exit(f"FAIL test-plan gate: {tp_id} is not approved")

    # Coverage heuristic (review finding 4): the referenced plan must
    # mention at least one changed implementation file by basename —
    # otherwise the reference is decorative (PR #39 referenced TP-012,
    # whose text never mentioned news.recent). Amend the TP in the same
    # change set; amendments are append-only sections.
    basenames = {pathlib.PurePosixPath(f).name for f in triggers}
    mentioned = {b for b in basenames if b in tp_text}
    if not mentioned:
        sys.exit(
            "FAIL test-plan gate: "
            f"{tp_id} mentions none of the changed files ({sorted(basenames)}); "
            "append an amendment section covering this change before merging"
        )
    print(
        f"PASS test-plan gate: {tp_id} referenced, approved, "
        f"and covers {sorted(mentioned)}"
    )

    # Safety-path memo attestation (review finding 1): changes to
    # guardrail / registry / shared / prompts / CI workflows require a
    # review-memo entry in the same change set; the PR body attests it.
    SAFETY_PREFIXES = (
        "src/stockinsider/agent/guardrail",
        "src/stockinsider/agent/registry",
        "src/stockinsider/shared/",
        "prompts/",
        ".github/workflows/",
    )
    safety_hits = [f for f in changed if f.startswith(SAFETY_PREFIXES)]
    if safety_hits:
        if "review-memo: appended" not in body.lower():
            sys.exit(
                "FAIL test-plan gate: safety-critical paths touched "
                f"({safety_hits}) but the PR body lacks 'Review-Memo: appended' "
                "(docs/review-memo.md entry in the same change set)"
            )
        # N2 (TP-017): the attestation must be backed by a real diff - an
        # entry in docs/review-memo.md must travel in the same change set.
        if not any(f == "docs/review-memo.md" for f in changed):
            sys.exit(
                "FAIL test-plan gate: safety-critical paths touched and the "
                "body attests a review memo, but docs/review-memo.md is NOT "
                "in this change set - append the entry, do not just claim it"
            )
        print("PASS test-plan gate: review-memo present in diff (safety path)")


if __name__ == "__main__":
    main()
