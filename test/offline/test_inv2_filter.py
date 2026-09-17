"""Adversarial INV-002 epistemic-filter suite (TP-006; 0 violating outputs pass).

Deterministic predictions and causal claims are stripped; labeled
speculation passes; the one-regeneration-then-refuse flow follows the
invariant document's fallback semantics.
"""

from stockinsider.agent.guardrail import (
    PostCheckCounter,
    epistemic_filter,
    run_postcheck,
    run_with_regeneration,
)


def test_deterministic_prediction_blocked() -> None:
    result = epistemic_filter("Tencent will rise after the earnings call.")
    assert result.passed is False
    assert result.clean_text == ""


def test_guaranteed_pattern_blocked() -> None:
    result = epistemic_filter("Shares are guaranteed to fall this quarter.")
    assert result.passed is False


def test_must_pattern_blocked() -> None:
    result = epistemic_filter("The stock must go up from here.")
    assert result.passed is False


def test_causal_claim_blocked() -> None:
    result = epistemic_filter("Because of the rate cut, the index rallied within days.")
    assert result.passed is False
    assert result.clean_text == ""


def test_labeled_speculation_passes() -> None:
    result = epistemic_filter("Hypothesis: the stock will rise if liquidity returns.")
    assert result.passed is True
    assert "Hypothesis:" in result.clean_text


def test_unlabeled_prediction_with_might_still_flagged_only_when_pattern() -> None:
    # "might" is a hypothesis marker AND not a pattern verb: passes trivially.
    result = epistemic_filter("The stock might rise if sentiment improves.")
    assert result.passed is True


def test_clean_analysis_passes() -> None:
    result = epistemic_filter("Revenue grew year over year, led by cloud services and advertising.")
    assert result.passed is True


def test_strip_removes_only_violations() -> None:
    text = "Margins are stable. The stock will fall soon. Cash flow improved."
    result = epistemic_filter(text)
    assert result.passed is False
    assert result.clean_text == "Margins are stable. Cash flow improved."
    assert result.violations == ["The stock will fall soon."]


def test_regeneration_recovers() -> None:
    outcome = run_with_regeneration(
        "It will surge.",
        lambda reminder: f"{reminder.splitlines()[0]} Revised: it may surge (hypothesis).",
    )
    assert outcome.refused is False
    assert "hypothesis" in outcome.displayed
    assert outcome.violations_total == 1


def test_regeneration_still_bad_refuses_with_safe_summary() -> None:
    outcome = run_with_regeneration("It will surge.", lambda _reminder: "It will definitely climb again.")
    assert outcome.refused is True
    assert outcome.displayed.startswith("refused:")
    assert "hypothesis:" in outcome.displayed
    assert outcome.violations_total == 2


def test_two_violation_budget_aborts() -> None:
    counter = PostCheckCounter()
    one_violation = run_postcheck("The stock will fall.", {})
    assert counter.record(one_violation) is None  # total 1
    two_more = run_postcheck("It will rise. The index will drop.", {})
    assert counter.record(two_more) == "abort:epistemic"  # total 3 > 2


def test_quarantine_takes_precedence_in_display() -> None:
    verdict = run_postcheck("The stock will fall to 42.", {"close": 311.4})
    assert verdict.quarantined is True  # fabricated number dominates
    assert verdict.display_text.startswith("data unavailable for:")
    assert verdict.epistemic.violations  # still recorded for the counter
