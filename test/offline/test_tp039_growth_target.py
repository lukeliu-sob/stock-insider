"""TP-039: growth phrasing and the "Target" name/cue collision (E-013 follow-up).

Unit cases run on the frozen E-013 ledgers (real tool shapes). E-014, written by a separately
briefed author before the rule code, measures the change; its pins are a regression baseline.

Implements: REQ-SI-INV-001, REQ-SI-QA-001 (ADR-008 Am2; TP-039)
"""

from __future__ import annotations

from test_tp025_stage5_e013 import FIXTURES, LEDGER_FILE, _load, _specs, evaluate, label_disagreements

from stockinsider.agent import guardrail

LEDGERS = _load(LEDGER_FILE)["ledgers"]
US, APPLE_ONLY = LEDGERS["us_pair"], LEDGERS["apple_only"]
E014_FILE = FIXTURES / "e014_heldout.yaml"
E014_CLASSES = ("growth_phrasing", "name_cue_collision")


def check(text: str, ledger: dict):
    return guardrail.postcheck_numbers(text, ledger, _specs())


def reasons(text: str, ledger: dict) -> dict[str, tuple[bool, str]]:
    return {claim.raw: (claim.verified, getattr(claim, "reason", "")) for claim in check(text, ledger).claims}


def test_year_on_year_is_a_growth_cue() -> None:
    assert reasons("Apple's revenue was 9.56% year on year.", US)["9.56"][0]
    assert reasons("Apple's revenue was 9.56% year-on-year.", US)["9.56"][0]
    assert not reasons("Apple's revenue was USD 9.56 billion.", US)["9.56"][0]


def test_revenue_change_verb_with_percent_is_growth() -> None:
    assert reasons("Apple's revenue rose 9.56%.", US)["9.56"][0]
    assert reasons("Target's revenue fell 1.18%.", US)["1.18"][0]
    assert reasons("Apple posted a 9.56% increase in revenue.", US)["9.56"][0]
    assert not reasons("Target's revenue grew 1.18%.", US)["1.18"][0]  # the ledger shows a decline
    assert not reasons("Apple's revenue of 9.56 billion was a record.", US)["9.56"][0]


def test_a_level_after_to_is_not_growth() -> None:
    found = reasons("Apple's revenue rose 9.56% year on year to USD 94.0 billion.", US)
    assert found["9.56"][0] and found["94.0"][0]
    assert not reasons("Apple's revenue rose 9.56% year on year to USD 95.0 billion.", US)["95.0"][0]


def test_ledger_name_is_not_a_field_label() -> None:
    table = (
        "| Company | Open | High | Low | Close |\n|---|---|---|---|---|\n"
        "| Target | 134.11 | 136.54 | 133.3 | {close} |"
    )
    assert all(verified for verified, _ in reasons(table.format(close="134.92"), US).values())
    verified, reason = reasons(table.format(close="139.99"), US)["139.99"]
    assert not verified and "price target" not in reason


def test_ledger_name_is_not_a_prose_cue() -> None:
    found = reasons("Closing prices: Target $134.92, Apple $234.42.", US)
    assert found["134.92"][0] and found["234.42"][0]


def test_price_target_still_has_no_evidence() -> None:
    for text in ("Target's target price of 150 looks stretched.", "Analysts set a price target of USD 160 for Apple."):
        flagged = [(raw, reason) for raw, (verified, reason) in reasons(text, US).items() if not verified]
        assert flagged and all("price target" in reason for _, reason in flagged), text


def test_name_rule_needs_the_name_in_the_ledger() -> None:
    table = "| Company | Close |\n|---|---|\n| Target | 134.92 |"
    verified, reason = reasons(table, APPLE_ONLY)["134.92"]
    assert not verified and "price target" in reason


# ---- E-014 ------------------------------------------------------------------------

#: Owner rulings on E-014's mechanical disagreements (2026-10-27): every label stands - F024's
#: cells take the scale stated in the table title; F010's 14.52% lies outside Tencent's growth at
#: the written precision and equals BYD's volatility. The author's own labeling rules are accepted.
E014_RULINGS: dict[tuple[str, str], str] = {
    ("F010", "14.52%"): "label stands",
    **{("F024", cell): "label stands" for cell in ("25.2", "0.94", "7.11", "23.8", "6.87", "30.9", "1.10")},
}

#: E-014 on the changed engine (2026-10-27). The first run, before the F012 fix, measured
#: precision 76/93; F012 ("rose 9.56% year on year to 94.0 billion") was a regression of the new
#: growth cue, fixed by owner decision and so no longer independent. Pre-change engine: 66/93.
E014_FALSE_FLAGS = {
    ("F007", "9.557%"), ("F011", "9.56%"),  # growth vocabulary: "top line expanded", "sales growth"
    ("F024", "25.2"), ("F024", "0.94"), ("F024", "7.11"), ("F024", "23.8"), ("F024", "6.87"), ("F024", "30.9"),
    ("F024", "1.10"),  # scale stated in the table title (option c, deferred)
    ("F023", "136.54"), ("F032", "3"), ("F035", "331 billion"), ("F039", "231.61"), ("F039", "237.23"),
    ("F047", "86.81"), ("F050", "58.0 billion"),
}


def test_e014_battery_shape() -> None:
    battery = _load(E014_FILE)
    claims = [(item, label) for item in battery["items"] for label in item["claims"]]
    assert len(claims) >= 60
    assert sum(not label["correct"] for _, label in claims) >= 25
    for name in E014_CLASSES:
        assert sum(label.get("class") == name for _, label in claims) >= 15, name
    for item, label in claims:
        assert item["text"].count(label["text"]) == 1, (item["id"], label["text"])
        assert item["ledger"] in LEDGERS, item["id"]


def test_e014_labels_agree_with_ledgers() -> None:
    disagreements = label_disagreements(_load(E014_FILE), LEDGERS)
    assert {entry[:2] for entry in disagreements} == set(E014_RULINGS)


def test_e014_heldout_measurement() -> None:
    result = evaluate(_load(E014_FILE), LEDGERS, E014_RULINGS)
    assert (len(result["correct"]), len(result["wrong"])) == (93, 34)
    assert result["escapes"] == []
    assert set(result["false_flags"]) == E014_FALSE_FLAGS, sorted(set(result["false_flags"]) ^ E014_FALSE_FLAGS)
    assert result["extra_flags"] == []
    for name, tally in sorted(result["by_class"].items()):
        print(name, tally)
