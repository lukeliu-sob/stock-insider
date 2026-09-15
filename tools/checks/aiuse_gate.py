#!/usr/bin/env python3
"""Change-set gate: AI-use log (blocking gate D7-6, GOV-002).

A PR that changes src/ or prompts/ must also change
docs/ai-use-log.yaml in the same change set.

Environment: CI_BASE_SHA (base commit). Without it, the gate skips
(local mode) — CI always provides it.
"""

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TRIGGER_PREFIXES = ("src/", "prompts/")
LOG = "docs/ai-use-log.yaml"


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
        print("PASS ai-use log gate: no CI_BASE_SHA (local mode, skipped)")
        return
    if not changed:
        print("PASS ai-use log gate: no changes")
        return

    triggers = [f for f in changed if f.startswith(TRIGGER_PREFIXES)]
    if triggers and LOG not in changed:
        sys.exit(
            f"FAIL ai-use log gate: change set touches {triggers} "
            f"without updating {LOG} (GOV-002 / D7-6)"
        )
    print("PASS ai-use log gate")


if __name__ == "__main__":
    main()
