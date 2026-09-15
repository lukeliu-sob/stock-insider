#!/usr/bin/env python3
"""Structural gate: language policy (GOV-001 / FR-014).

CJK characters are forbidden in repository artifacts outside the
exemption list:
  - CS5351-2026-2027-project.md, agent-era-RE-methodology.md
    (course source materials, not project artifacts)
  - docs/req/glossary.md (contains the documented alias exception)
Runtime state (data/, sessions/) and VCS internals are skipped.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

EXEMPT_FILES = {
    "CS5351-2026-2027-project.md",
    "agent-era-RE-methodology.md",
    pathlib.PurePosixPath("docs/req/glossary.md").as_posix(),
}
SKIP_DIRS = {
    ".git",
    "data",
    "sessions",
    "node_modules",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "npm",
}
SCAN_EXT = {
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
    ".gitignore",
    ".yml",
}

CJK = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff01-\uff5e]")


def iter_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXEMPT_FILES:
            continue
        if any(part in SKIP_DIRS for part in pathlib.PurePosixPath(rel).parts):
            continue
        if path.suffix in SCAN_EXT or path.name == ".gitignore":
            yield path, rel


def main() -> None:
    violations = []
    for path, rel in iter_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if CJK.search(line):
                violations.append(f"{rel}:{lineno}")
    if violations:
        sys.exit("FAIL language policy, CJK found at: " + ", ".join(violations[:20]))
    print("PASS language policy: no CJK outside exemptions")


if __name__ == "__main__":
    main()
