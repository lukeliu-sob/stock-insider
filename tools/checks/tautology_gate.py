"""Tautology gate: no always-true assertions in tests (review finding 9).

Scans test/ for `or True`, `and False`, and bare `assert True` —
patterns that make an assertion unfalsifiable. The gate exists
because two such assertions shipped in BD-018's test suite and a
third-party review caught them; its first run found two more.

Implements: REQ-SI-GOV-006 (ADR-001)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PATTERNS = (
    re.compile(r"\bor\s+True\b"),
    re.compile(r"\band\s+False\b"),
    re.compile(r"assert\s+True\b"),
)


def main() -> None:
    """Fail if any test line makes an assertion unfalsifiable."""
    offenders: list[str] = []
    for path in (ROOT / "test").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue  # comment lines can mention the patterns
            if any(p.search(line) for p in PATTERNS):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:90]}")
    if offenders:
        print("FAIL tautology gate: unfalsifiable assertions found:")
        for entry in offenders:
            print(f"  {entry}")
        sys.exit(1)
    print("PASS tautology gate: no always-true assertions in test/")


if __name__ == "__main__":
    main()
