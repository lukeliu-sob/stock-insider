"""Adversarial INV-001 post-check suite (TP-006; 0-escape by design).

lang-fixture: intentional-cjk (the language-violation case needs real CJK).

Fabricated numbers must never pass; correctly cited numbers pass 100%;
boundary ±1 fails; quarantine and degradation semantics per the
invariant document.
"""

from stockinsider.agent.guardrail import (
    PostCheckCounter,
    extract_numbers,
    postcheck_numbers,
    run_postcheck,
)


def test_fabricated_number_rejected() -> None:
    check = postcheck_numbers("The close was 42.0 today.", {"quote": {"close": 311.4}})
    assert check.passed is False
    assert check.failed == ["42.0"]


def test_cited_number_passes() -> None:
    check = postcheck_numbers("The close was 311.4.", {"quote": {"close": 311.4}})
    assert check.passed is True and check.matched == ["311.4"]


def test_boundary_plus_minus_one_fails() -> None:
    below = postcheck_numbers("close 311.4", {"close": 311.5})
    exact = postcheck_numbers("close 311.5", {"close": 311.5})
    assert below.passed is False
    assert exact.passed is True


def test_multiple_failures_all_listed() -> None:
    check = postcheck_numbers("pe is 42 and pb is 7.7", {"fundamentals": {"pe": 30.1}})
    assert check.passed is False
    assert sorted(check.failed) == ["42", "7.7"]


def test_thousands_separator_normalized() -> None:
    check = postcheck_numbers("revenue 1,234.5", {"revenue": 1234.5})
    assert check.passed is True


def test_int_float_equivalence() -> None:
    check = postcheck_numbers("budget 30000", {"budget": 30000.0})
    assert check.passed is True


def test_nested_snapshot_walk() -> None:
    snapshot = {"quote": {"levels": [311.4, 309.0]}, "meta": "as of turn 7"}
    check = postcheck_numbers("traded 311.4 and 309.0", snapshot)
    assert check.passed is True


def test_string_values_are_walked() -> None:
    check = postcheck_numbers("level 309.0", {"note": "support level 309.0 held"})
    assert check.passed is True


def test_zero_numbers_passes_trivially() -> None:
    check = postcheck_numbers("no numerals anywhere", {"x": 1})
    assert check.passed is True and check.failed == []


def test_extract_numbers_shapes() -> None:
    assert extract_numbers("3.2% of $1,234.56 at -2.5") == ["3.2", "1234.56", "-2.5"]


def test_verdict_quarantines_and_degrades() -> None:
    verdict = run_postcheck("The close was 42.0.", {"close": 311.4})
    assert verdict.quarantined is True
    assert verdict.degraded == "data unavailable for: 42.0"
    assert verdict.display_text == verdict.degraded


def test_verdict_clean_pass() -> None:
    candidate = "The close was 311.4, up from 309.0."
    verdict = run_postcheck(candidate, {"close": 311.4, "prev": 309.0})
    assert verdict.quarantined is False
    assert verdict.display_text == candidate
    assert verdict.violations == []


def test_language_violation_quarantines() -> None:
    verdict = run_postcheck("这一句没有数字", {"x": 1})
    assert verdict.quarantined is True
    assert verdict.language_ok is False
    assert "language policy" in verdict.display_text


def test_counter_three_strikes_then_abort() -> None:
    counter = PostCheckCounter()
    bad = run_postcheck("close was 42.0", {"close": 311.4})
    assert counter.record(bad) is None
    assert counter.record(bad) is None
    assert counter.record(bad) == "abort:number"


def test_counter_resets_on_pass() -> None:
    counter = PostCheckCounter()
    bad = run_postcheck("close was 42.0", {"close": 311.4})
    good = run_postcheck("close was 311.4", {"close": 311.4})
    counter.record(bad)
    counter.record(bad)
    assert counter.record(good) is None  # streak reset
    assert counter.record(bad) is None
    assert counter.record(bad) is None  # streak is only 2 again
