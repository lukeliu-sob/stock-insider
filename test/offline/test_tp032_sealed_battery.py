"""DE-09 (TP-032): the second held-out INV-002 battery, sealed before the pattern change.

The battery was written by a separately briefed session (TP-032, P6). This module checks its
structure, its independence from the development battery (TP-030), and its seal: the
LF-normalized SHA-256 must match the value recorded in TP-032. It runs no measurement. The
baseline is recorded in TP-032, and the post-fix measurement is the fix's acceptance test.

Implements: REQ-SI-INV-002 (ADR-006 Am8; TP-032)
"""

import collections
import hashlib
import json
import re
from pathlib import Path

SEALED = Path(__file__).parent / "fixtures" / "inv002_sealed_tp032.json"
DEVELOPMENT = Path(__file__).parent / "fixtures" / "inv002_heldout_tp030.json"
SEAL_SHA256 = "b2625419a7ca908fb110dfbf2279cb4877af0079014ea98d983d33dc675ab243"
FLAG_CLASSES = ("mis-scoped-hedge", "fabricated-attribution", "unanticipated-paraphrase")
PASS_CLASSES = ("control-hypothesis", "control-scoped-hedge", "control-factual")


def normalized_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def load(path: Path) -> list[dict]:
    return json.loads(normalized_bytes(path).decode("utf-8"))


def words(sentence: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", sentence.lower()))


def jaccard(left: str, right: str) -> float:
    left_words, right_words = words(left), words(right)
    return len(left_words & right_words) / len(left_words | right_words)


def test_sealed_battery_is_well_formed() -> None:
    items = load(SEALED)
    assert len(items) == 60
    assert all(set(item) == {"id", "sentence", "expected", "gap_class", "rationale"} for item in items)
    counts = collections.Counter((item["expected"], item["gap_class"]) for item in items)
    assert all(counts[("flag", gap_class)] == 10 for gap_class in FLAG_CLASSES)
    assert all(counts[("pass", gap_class)] == 10 for gap_class in PASS_CLASSES)
    assert [item["id"] for item in items] == [f"SB-{number:03d}" for number in range(1, 61)]
    assert len({item["sentence"] for item in items}) == 60
    assert all(item["sentence"].isascii() for item in items)
    assert all(len(re.split(r"(?<=[.!?])\s+", item["sentence"].strip())) == 1 for item in items)


def test_sealed_battery_is_unchanged() -> None:
    assert hashlib.sha256(normalized_bytes(SEALED)).hexdigest() == SEAL_SHA256


def test_no_overlap_with_development_battery() -> None:
    development = load(DEVELOPMENT)
    dev_sentences = {item["sentence"].strip().lower() for item in development}
    sealed = load(SEALED)
    exact = [item["id"] for item in sealed if item["sentence"].strip().lower() in dev_sentences]
    near = [
        (item["id"], other["id"])
        for item in sealed
        for other in development
        if jaccard(item["sentence"], other["sentence"]) >= 0.6
    ]
    assert not exact
    assert not near
