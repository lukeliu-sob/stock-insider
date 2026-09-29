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
        encoding="utf-8",  # TP-018: repo diffs are UTF-8; the platform
        errors="replace",  # default codec (GBK on zh-CN Windows) crashed
        check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def added_memo_headings() -> list[str]:
    """New '### RM-' heading lines in the docs/review-memo.md diff.

    new-7 (TP-018): the memo check must see a REAL entry, not file
    churn — appending a blank line to docs/review-memo.md used to
    satisfy "the file is in the diff".
    """
    base = os.environ.get("CI_BASE_SHA")
    if not base:
        return []
    out = subprocess.run(
        ["git", "diff", f"{base}...HEAD", "--", "docs/review-memo.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",  # memo text carries typographic UTF-8
        errors="replace",
        check=True,
    ).stdout
    return [
        line[1:].strip()
        for line in out.splitlines()
        if line.startswith("+") and line[1:].lstrip().startswith("### RM-")
    ]


SAFETY_PREFIXES = (
    "src/stockinsider/agent/guardrail",
    "src/stockinsider/agent/registry",
    "src/stockinsider/shared/",
    "prompts/",
    ".github/workflows/",
)


def safety_memo_check(changed: list[str], body: str) -> None:
    """Safety-path change sets carry a real review-memo entry.

    new-7 (TP-018): this check runs BEFORE the "no implementation
    files" early return — a prompts/-only or workflow-only change set
    is exactly the safety-relevant case the old ordering waved through
    (nothing under src/ or test/ -> PASS without ever reaching this
    block). Requires: body attestation + the memo file in the diff +
    at least one ADDED '### RM-' heading (blank-line padding fails).
    """
    safety_hits = [f for f in changed if f.startswith(SAFETY_PREFIXES)]
    if not safety_hits:
        return
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
    # new-7 (TP-018): the diff must ADD a real entry heading, not merely
    # touch the file (blank-line padding used to pass).
    import re as _re

    headings = [h for h in added_memo_headings() if _re.search(r"RM-" + chr(92) + "d+", h)]
    if not headings:
        sys.exit(
            "FAIL test-plan gate: docs/review-memo.md is in the change set "
            "but the diff adds no '### RM-' entry heading - append a real "
            "entry for this change set"
        )
    print(f"PASS test-plan gate: review-memo entries added (safety path): {headings}")


def main() -> None:
    changed = changed_files()
    body = os.environ.get("PR_BODY")
    if changed is None:
        print("PASS test-plan gate: non-PR context (skipped)")
        return
    if not body:
        # Fourth-audit finding (TP-018b): CI_BASE_SHA is set, so this IS
        # a PR context - an empty body cannot reference a test plan nor
        # attest a review memo. Skipping here waved through PRs whose
        # entire change set never met the gate.
        sys.exit(
            "FAIL test-plan gate: PR context (CI_BASE_SHA set) but PR_BODY "
            "is empty - the PR must reference 'Test-Plan: TP-NNN' (GOV-006)"
        )

    # Safety-path memo attestation runs FIRST (new-7, TP-018): it must
    # hold even when no implementation file is touched.
    safety_memo_check(changed, body)

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
    print(f"PASS test-plan gate: {tp_id} referenced, approved, and covers {sorted(mentioned)}")


if __name__ == "__main__":
    main()
