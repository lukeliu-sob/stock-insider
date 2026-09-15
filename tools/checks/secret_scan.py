#!/usr/bin/env python3
"""Structural gate: secret scan (blocking gate D7-2, pattern level).

Fails on common credential patterns in tracked text files and on any
committed .env file. Pattern-level only — full-history scanning and
push protection remain GitHub-side responsibilities.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKIP_DIRS = {
    ".git",
    "data",
    "sessions",
    "node_modules",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}

PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)(api_key|secret|password|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
    ),
]


def main() -> None:
    if (ROOT / ".env").exists():
        sys.exit("FAIL secret scan: .env file is committed (SEC-001)")

    violations = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(part in SKIP_DIRS for part in pathlib.PurePosixPath(rel).parts):
            continue
        if path.suffix not in {
            ".py",
            ".md",
            ".yaml",
            ".yml",
            ".json",
            ".jsonc",
            ".ts",
            ".toml",
            ".txt",
            ".cfg",
        }:
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
    print("PASS secret scan (pattern level)")


if __name__ == "__main__":
    main()
