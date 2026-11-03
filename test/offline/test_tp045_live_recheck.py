"""TP-045: false flags found when verifying TP-040..044 on a copy of the real store.

Unit cases take the shapes of the verification run's live answers, on the frozen E-015 ledgers.
E-013, E-014 and E-015 are development sets now and run as regression only (their own pins);
no independent battery measures this change (disclosed in the plan).

Implements: REQ-SI-INV-001, REQ-SI-QA-001 (ADR-008 Am3; TP-045)
"""

from __future__ import annotations

from test_tp025_stage5_e013 import _specs
from test_tp042_live_false_flags import BYD, PERF

from stockinsider.agent import guardrail


def _verdicts(text: str, ledger: dict) -> dict[str, bool]:
    return {claim.raw: claim.verified for claim in guardrail.postcheck_numbers(text, ledger, _specs()).claims}


def test_hyphenated_count_is_a_count() -> None:
    good = _verdicts("BYD's max drawdown of -18.24% sits within the 259-session history.", BYD)
    assert all(good.values()), good
    assert not _verdicts("BYD's max drawdown of -18.24% sits within the 258-session history.", BYD)["258"]


def test_session_range_is_not_a_count() -> None:
    good = _verdicts("BYD closed at 75.07, inside the 74.47–75.9 session range.", BYD)
    assert all(good.values()), good
    assert not _verdicts("BYD closed at 75.07, inside the 74.47–76.9 session range.", BYD)["76.9"]
    # "session" before high/low names the bar, not a count (E-014 F023's shape)
    assert all(_verdicts("BYD closed at 75.07, below its 75.9 session high.", BYD).values())
    assert not _verdicts("BYD closed at 75.07, below its 76.9 session high.", BYD)["76.9"]


def test_percent_after_price_cue_is_a_change() -> None:
    good = _verdicts("Tencent's adjusted close fell 4.88% over the last 20 sessions.", PERF)
    assert all(good.values()), good
    assert not _verdicts("Tencent's adjusted close is 4.88.", PERF)["4.88"]


def test_nearest_count_selects_the_window() -> None:
    good = _verdicts(
        "Tencent's 60-session figure (-6.58%) is a larger decline than its 20-session figure (-4.88%).", PERF
    )
    assert all(good.values()), good
    swapped = _verdicts(
        "Tencent's 60-session figure (-4.88%) is a smaller decline than its 20-session figure (-6.58%).", PERF
    )
    assert not swapped["-4.88"] and not swapped["-6.58"]


def test_compared_number_inherits_the_decline() -> None:
    rose = _verdicts("Over the last 20 sessions Tencent fell 4.88% versus 3.34% for the index.", PERF)
    assert rose["4.88"] and not rose["3.34"]  # the index rose 3.34% over 20 sessions
    # the subject stands before the number: one written after it ("0.32% for the index")
    # is the postposed-subject residual (DE-15, option d), not this rule
    fell = _verdicts("Over 250 sessions Tencent fell 10.61% versus the index's 0.32%.", PERF)
    assert all(fell.values()), fell


def test_bare_index_names_the_index() -> None:
    good = _verdicts("Over 5 sessions Tencent rose 1.89%, against an essentially flat index (+1.10%).", PERF)
    assert all(good.values()), good
    wrong = _verdicts("Over 5 sessions the HSI rose 1.10%, against an essentially flat index (+1.89%).", PERF)
    assert not wrong["1.89"]  # Tencent's change given to the index


def test_section_number_is_layout() -> None:
    assert _verdicts("No attribution of the moves in Section 2 is made.", BYD) == {}
    assert "2" in _verdicts("The report has 2 sections.", BYD)


def test_stated_window_noun_names_a_change() -> None:
    """"a 20-session window of -4.88%" after a volatility cue is the change, not the volatility."""
    good = _verdicts(
        "A volatility of 7.21% implies that a 20-session window of -4.88% is not an outlier.", PERF
    )
    assert good["-4.88"], good
    assert not _verdicts("A volatility of 7.21% implies that a 20-session window of -6.58% is ordinary.", PERF)["-6.58"]


def test_tool_key_before_number_types_it() -> None:
    good = _verdicts("The adjusted close declined (change_pct -4.8828, 20 sessions).", PERF)
    assert good["-4.8828"], good
    assert not _verdicts("The adjusted close declined (change_pct -4.8282, 20 sessions).", PERF)["-4.8282"]
