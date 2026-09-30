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


def log_structure_errors(text: str) -> list[str]:
    """Structural problems in the AI-use log (TP-019, BD-025).

    PR #54 appended two entries at column 0 and the mandatory audit
    record silently stopped being valid YAML - this gate only checked
    that the file was in the change set. The log must parse, keep its
    `sessions` list, and carry unique well-formed AILOG-NNNN ids.
    """
    import re

    import yaml

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"not parseable as YAML: {str(exc).splitlines()[0]}"]
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
        return ["top level must be a mapping with a 'sessions' list"]
    errors: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(data["sessions"], start=1):
        entry_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(entry_id, str) or not re.fullmatch(r"AILOG-\d{4}", entry_id):
            errors.append(f"entry #{index} has a malformed id: {entry_id!r}")
        elif entry_id in seen:
            errors.append(f"duplicate id {entry_id}")
        else:
            seen.add(entry_id)
    return errors


def _fail_on_structure() -> None:
    errors = log_structure_errors((ROOT / LOG).read_text(encoding="utf-8"))
    if errors:
        sys.exit(f"FAIL ai-use log gate: {LOG} is structurally broken: {errors[:5]} (GOV-002)")


def main() -> None:
    changed = changed_files()
    if changed is None:
        _fail_on_structure()
        print("PASS ai-use log gate: no CI_BASE_SHA (local mode; change-set check skipped, structure ok)")
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
    if LOG in changed:
        _fail_on_structure()
    print("PASS ai-use log gate")


if __name__ == "__main__":
    main()
