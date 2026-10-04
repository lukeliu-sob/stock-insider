"""DE-09 (TP-033): the epistemic filter's clause scope and certainty predicates.

Mechanism 1: a reporting or cognition verb followed by "that", "why" or "whether" opens a
new clause for hedge scope. Mechanism 2: a certainty construction is a deterministic claim
only with a price or performance predicate after it. Institutional speech stays exempt, and
generic attribution tags stay non-institutional.

The development battery (TP-030) is read here only to check its controls for false flags.
The sealed battery (TP-032) is the acceptance measurement of TP-033.

Implements: REQ-SI-INV-002 (ADR-006 Am8, Am11; TP-033)
"""

import json
from pathlib import Path

from stockinsider.agent.guardrail import epistemic_filter

DEVELOPMENT = Path(__file__).parent / "fixtures" / "inv002_heldout_tp030.json"
SEALED = Path(__file__).parent / "fixtures" / "inv002_sealed_tp032.json"


def flagged(sentence: str) -> bool:
    return not epistemic_filter(sentence).passed


def test_complement_of_reporting_hedge_is_flagged() -> None:
    assert flagged("Some analysts may suggest that Alibaba shares will climb past 200 HKD next year.")


def test_direct_hedge_on_complement_still_passes() -> None:
    assert not flagged("It may be that Alibaba shares will climb past 200 HKD next year.")


def test_certainty_construction_with_predicate_is_flagged() -> None:
    assert flagged("Analysts say the stock is bound to climb 5 percent next quarter.")


def test_certainty_construction_without_predicate_passes() -> None:
    assert not flagged("The company is set to report its quarterly results on 12 November.")


def test_certainty_idiom_with_predicate_is_flagged() -> None:
    assert flagged("There is no doubt that the shares will slide 15 percent before summer.")


def test_will_level_outcome_is_flagged() -> None:
    assert flagged("The index will push back above 6,000 points by March.")


def test_generic_attribution_does_not_excuse() -> None:
    assert flagged("The consensus view is that Alibaba shares will climb past 200 HKD next year.")


def test_institutional_speech_still_excuses() -> None:
    assert not flagged("The company announced that revenue will decline next year.")


def test_development_battery_controls_keep_zero_false_flags() -> None:
    controls = [item for item in json.loads(DEVELOPMENT.read_text(encoding="utf-8")) if item["expected"] == "pass"]
    false_flags = [item["id"] for item in controls if flagged(item["sentence"])]
    assert not false_flags


def test_sealed_battery_meets_target() -> None:
    # Acceptance target set by the owner on 2026-10-04. Measured once after the fix:
    # 14 of 30 (47%) with zero false flags (TP-033 Result). This assertion is red until
    # the owner decides how to proceed; it is not to be weakened to pass.
    sealed = json.loads(SEALED.read_text(encoding="utf-8"))
    flag_items = [item for item in sealed if item["expected"] == "flag"]
    pass_items = [item for item in sealed if item["expected"] == "pass"]
    caught = sum(flagged(item["sentence"]) for item in flag_items)
    false_flags = sum(flagged(item["sentence"]) for item in pass_items)
    assert caught / len(flag_items) >= 0.80
    assert false_flags == 0
