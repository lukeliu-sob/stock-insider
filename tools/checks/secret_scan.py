#!/usr/bin/env python3
"""Structural gate: secret scan (blocking gate D7-2, pattern level).

Fails on common credential patterns in tracked text files and when a
.env file is tracked by git (SEC-001). A local untracked .env is the
supported development flow (loaded by the product with dotenv
semantics) and does NOT fail this gate. Pattern-level only —
full-history scanning and push protection remain GitHub-side
responsibilities.
"""

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "data", "sessions", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache"}

PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api_key|secret|password|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
]


def main() -> None:
    tracked: list[str] = []
    try:
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
    except (subprocess.CalledProcessError, OSError):
        # No git metadata (e.g., an exported tree): nothing can be tracked.
        tracked = []
    if ".env" in tracked:
        sys.exit("FAIL secret scan: .env is tracked by git (SEC-001)")

    violations = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in tracked and rel == ".env":
            continue  # unreachable; guarded above
        if any(part in SKIP_DIRS for part in pathlib.PurePosixPath(rel).parts):
            continue
        if path.suffix not in {".py", ".md", ".yaml", ".yml", ".json", ".jsonc", ".ts", ".toml", ".txt", ".cfg"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pat in PATTERNS:
            m = pat.search(text)
            if m:
                violations.append(f"{rel}: pattern {pat.pattern[:25]}...")
                break

    if violations:
        sys.exit("FAIL secret scan:\n  " + "\n  ".join(violations[:20]))
    print("PASS secret scan (pattern level; local untracked .env allowed)")


if __name__ == "__main__":
    main()
