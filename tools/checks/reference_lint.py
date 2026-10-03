#!/usr/bin/env python3
"""Structural gate: cross-file ID reference validity (DE-06).

Governance artifacts cite each other by ID (DE-NN, TP-NNN, RM-NN, ADR-NNN,
REQ-SI-XXX-NNN). The references are human-maintained prose, and BD-4 showed
the class of error: a citation to an ID that was never defined, or whose
defining artifact was renamed. This gate collects every such token cited
anywhere under docs/ or in architecture-blueprint.md, and fails if a token
has no matching entry in its home artifact.

Runs unconditionally (whole-tree consistency, not a per-PR diff check), on
the tracked file list (`git ls-files`), so it never sees the local, gitignored
`proposals/` tree that trips the language-policy gate.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]

_DE = re.compile(r"\bDE-(\d+)\b")
_TP = re.compile(r"\bTP-(\d{3}[a-z]?)\b")
_RM = re.compile(r"\bRM-(\d+)\b")
_ADR = re.compile(r"\bADR-(\d{3})\b")
_REQ = re.compile(r"\bREQ-SI-[A-Z]+-\d{3}\b")

_DE_HEADING = re.compile(r"(?m)^#{1,4}\s+DE-(\d+)\b")
#: review-memo.md defines an entry either as a "### RM-NN" heading (the
#: current template) or, for the earliest entries, a "- RM-N — ..." backfill
#: index line (docs/review-memo.md:266+, predating the template).
_RM_HEADING = re.compile(r"(?m)^(?:#{1,4}|-)\s+RM-(\d+)\b")

#: Deliberate forward references to work the debt register/ADR-008 already
#: name as planned-but-not-yet-written (not a dangling citation - pin by
#: name, same convention as a detector's accepted residual elsewhere in
#: this repo, e.g. TP-024's H023 pins).
_FORWARD_REFS = {"TP": {"025"}}


def _tracked_docs() -> list[pathlib.Path]:
    out = subprocess.run(
        ["git", "ls-files", "docs", "architecture-blueprint.md"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [ROOT / line.strip() for line in out.splitlines() if line.strip()]


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def _known_de(debt_register: str) -> set[str]:
    return set(_DE_HEADING.findall(debt_register))


def _known_rm(review_memo: str) -> set[str]:
    return set(_RM_HEADING.findall(review_memo))


def _known_tp() -> tuple[set[str], set[str]]:
    """(exact ids, numeric bases) of every docs/test-plans/TP-*.md file.

    A base covers a letter-suffixed citation to a plan whose work is filed
    under the bare number (TP-011a cited, only TP-011.md exists) and the
    reverse (TP-007 cited, only TP-007a.md/TP-007b.md exist) - both are the
    same plan family, not a dangling reference.
    """
    out = subprocess.run(
        ["git", "ls-files", "docs/test-plans"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    exact: set[str] = set()
    bases: set[str] = set()
    for line in out.splitlines():
        name = pathlib.PurePosixPath(line.strip()).stem
        match = re.fullmatch(r"TP-(\d{3})([a-z]?)", name)
        if match:
            exact.add(match.group(1) + match.group(2))
            bases.add(match.group(1))
    return exact, bases


def _known_adr() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", "docs/architecture/adr"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    known = set()
    for line in out.splitlines():
        name = pathlib.PurePosixPath(line.strip()).stem
        match = re.match(r"(\d{3})-", name)
        if match:
            known.add(match.group(1))
    return known


def _known_req() -> set[str]:
    data = yaml.safe_load(_read(ROOT / "docs" / "req" / "requirements.yaml"))
    known: set[str] = set()

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            value = node.get("id")
            if isinstance(value, str) and _REQ.fullmatch(value):
                known.add(value)
            for child in node.values():
                _walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                _walk(child)

    _walk(data)
    return known


def find_dangling(files: dict[str, str], known: dict[str, set[str]], tp_bases: set[str]) -> list[str]:
    """Every citation in `files` with no matching entry in `known` (pure; no I/O).

    `files` maps a display path to its text; `known` holds the defined ids
    per prefix (DE/TP/RM/ADR/REQ, exactly as `main` assembles them); `tp_bases`
    is the set of 3-digit TP numbers with at least one file, letter-suffixed
    or not (see `_known_tp`).
    """
    dangling: list[str] = []
    for rel, text in files.items():
        for match in _DE.finditer(text):
            if match.group(1) not in known["DE"]:
                dangling.append(
                    f"{rel}: DE-{match.group(1)} (no '### DE-{match.group(1)}' heading in debt-register.md)"
                )
        for match in _TP.finditer(text):
            token = match.group(1)
            base = token[:3]
            if token in known["TP"] or base in tp_bases or token in _FORWARD_REFS["TP"]:
                continue
            dangling.append(f"{rel}: TP-{token} (no docs/test-plans/TP-{base}*.md)")
        for match in _RM.finditer(text):
            if match.group(1) not in known["RM"]:
                dangling.append(f"{rel}: RM-{match.group(1)} (no '### RM-{match.group(1)}' heading in review-memo.md)")
        for match in _ADR.finditer(text):
            if match.group(1) not in known["ADR"]:
                dangling.append(f"{rel}: ADR-{match.group(1)} (no docs/architecture/adr/{match.group(1)}-*.md)")
        for match in _REQ.finditer(text):
            if match.group() not in known["REQ"]:
                dangling.append(f"{rel}: {match.group()} (no matching id in requirements.yaml)")
    return dangling


def main() -> None:
    files = _tracked_docs()
    debt_register = _read(ROOT / "docs" / "debt-register.md")
    review_memo = _read(ROOT / "docs" / "review-memo.md")
    tp_exact, tp_bases = _known_tp()
    known = {
        "DE": _known_de(debt_register),
        "TP": tp_exact,
        "RM": _known_rm(review_memo),
        "ADR": _known_adr(),
        "REQ": _known_req(),
    }
    text_by_path = {path.relative_to(ROOT).as_posix(): _read(path) for path in files}
    dangling = sorted(set(find_dangling(text_by_path, known, tp_bases)))
    if dangling:
        sys.exit("FAIL reference lint: dangling citations:\n  " + "\n  ".join(dangling[:20]))
    print(
        f"PASS reference lint: {sum(len(v) for v in known.values())} known ids, "
        f"{len(files)} docs files scanned, no dangling citations"
    )


if __name__ == "__main__":
    main()
