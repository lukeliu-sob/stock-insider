"""DE-09 (TP-030): held-out INV-002 battery, measured against the current epistemic filter.

The battery was authored by a separately briefed session (TP-030, P6); its labels are
not tuned to any measurement. This module checks the battery and prints the baseline
table. It asserts no recall threshold: the owner sets the target before any pattern change.

Implements: REQ-SI-INV-002 (ADR-006 Am8; TP-030)
"""

import collections
import json
from pathlib import Path

from stockinsider.agent.guardrail import epistemic_filter

BATTERY = Path(__file__).parent / "fixtures" / "inv002_heldout_tp030.json"
FLAG_CLASSES = ("mis-scoped-hedge", "fabricated-attribution", "unanticipated-paraphrase")
PASS_CLASSES = ("control-hypothesis", "control-scoped-hedge", "control-factual")


def load_battery() -> list[dict]:
    return json.loads(BATTERY.read_text(encoding="utf-8"))


def test_inv002_heldout_battery_is_well_formed() -> None:
    items = load_battery()
    assert len(items) == 60
    assert all(set(item) == {"id", "sentence", "expected", "gap_class", "rationale"} for item in items)
    counts = collections.Counter((item["expected"], item["gap_class"]) for item in items)
    assert all(counts[("flag", gap_class)] == 10 for gap_class in FLAG_CLASSES)
    assert all(counts[("pass", gap_class)] == 10 for gap_class in PASS_CLASSES)
    assert [item["id"] for item in items] == [f"HO-{number:03d}" for number in range(1, 61)]
    assert len({item["sentence"] for item in items}) == 60
    assert all(item["sentence"].isascii() for item in items)


def test_measure_current_filter() -> None:
    tally: dict[str, list[int]] = collections.OrderedDict()
    for item in load_battery():
        flagged = not epistemic_filter(item["sentence"]).passed
        row = tally.setdefault(item["gap_class"], [0, 0])
        row[0] += 1
        row[1] += flagged
    for gap_class, (total, flagged) in tally.items():
        print(f"{gap_class:26s} n={total:2d} filter_flags={flagged:2d}")
    flag_total = sum(total for gap_class, (total, _) in tally.items() if gap_class in FLAG_CLASSES)
    flag_caught = sum(flagged for gap_class, (_, flagged) in tally.items() if gap_class in FLAG_CLASSES)
    pass_flagged = sum(flagged for gap_class, (_, flagged) in tally.items() if gap_class in PASS_CLASSES)
    print(f"recall on flag set: {flag_caught}/{flag_total}; false flags on pass set: {pass_flagged}/30")
    assert sum(total for total, _ in tally.values()) == 60
