"""TP-024: INV-001 v2 phase 2 - typed claim verification (ADR-008 Amendment 1).

Numbers are read as claims: a quantity with a field cue is compared with
evidence of its subject and field at its written precision; a quantity
without one keeps the v1 rule; times are parsed whole; quotations verify
against tool text; tickers, period labels and layout numbering are not
claims. Only unverified claims carry the marker, each with one reason.
The engine module is reached through `guardrail` (and imported lazily
where needed), so against the pre-change tree each test fails on its own.

Implements: REQ-SI-INV-001, REQ-SI-QA-001, REQ-SI-FR-022 (ADR-008)
"""

from __future__ import annotations

import dataclasses
import importlib
import random
import re
from pathlib import Path

import pytest
import yaml

from stockinsider.agent import guardrail
from stockinsider.agent.providers import ChatOutcome
from stockinsider.agent.session import SessionStore
from test_agent_loop import IDENTITY, Spy, make_engine

FIXTURES = Path(__file__).parent / "fixtures"
DEV = yaml.safe_load((FIXTURES / "e010_dev.yaml").read_text(encoding="utf-8"))
HELD_OUT = yaml.safe_load((FIXTURES / "e010_heldout.yaml").read_text(encoding="utf-8"))
LEDGERS = DEV["ledgers"]
BYD, PAIR, SESSION, FUND = (LEDGERS[name] for name in ("byd", "pair", "session", "fundamentals"))
MARK = "[?]"


@pytest.fixture()
def prompts_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "identity.md").write_text(IDENTITY, encoding="utf-8")
    return directory


@pytest.fixture()
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(root=tmp_path / "sessions")


def _check(text: str, ledger: object):
    return guardrail.postcheck_numbers(text, ledger)


def _claim(text: str, ledger: object, raw: str, occurrence: int = 0):
    found = [claim for claim in getattr(_check(text, ledger), "claims", []) if claim.raw == raw]
    assert len(found) > occurrence, (text, raw, [c.raw for c in getattr(_check(text, ledger), "claims", [])])
    return found[occurrence]


def _verified(text: str, ledger: object, raw: str) -> bool:
    return bool(_claim(text, ledger, raw).verified)


# ---- the ADR-008 probe and the live drivers --------------------------------------


def test_probe_correct_renderings_verify() -> None:
    for text, raw in (
        ("1211.HK traded 18.98 million shares.", "18.98"),
        ("1211.HK fell 36.09% from its peak.", "36.09"),
        ("Volatility is about 37%.", "37"),
        ("The article was published at 2026-09-29 12:32:02 UTC.", "2026-09-29 12:32:02 UTC"),
        ("BYD shows roughly a 37% annualized swing rate.", "37"),
    ):
        check = _check(text, BYD)
        assert check.passed, (text, check.failed)
        assert _verified(text, BYD, raw), text
    assert _check("Volatility is about 37%.", BYD).rounded == ["37"]


def test_probe_misattributions_flagged_with_reasons() -> None:
    cases = [
        ("BYD trades at a P/E of 18.", BYD, "18", "the tool reported P/E unavailable for 1211.HK"),
        ("0700.HK closed at 75.6.", PAIR, "75.6", "this close belongs to 1211.HK"),
        ("BYD's net margin is 0.998.", BYD, "0.998", "the tool reported net margin unavailable for 1211.HK"),
        (
            "Quarterly revenue was 380,000 million yuan.", BYD, "380,000",
            "the tool reported revenue unavailable for 1211.HK",
        ),
        ("BYD sold 380,000 vehicles in September.", BYD, "380,000", "appears only in tool text; quote it to cite it"),
    ]
    for text, ledger, raw, reason in cases:
        claim = _claim(text, ledger, raw)
        assert claim.verified is False, text
        assert claim.reason == reason, (text, claim.reason)


def test_live_millisecond_timestamp_is_more_precise() -> None:
    for text, raw in (
        ("It was published 20260929T123202178Z.", "20260929T123202178Z"),
        ("It was published at 2026-09-29 12:32:02.5 UTC.", "2026-09-29 12:32:02.5 UTC"),
    ):
        claim = _claim(text, BYD, raw)
        assert claim.verified is False and claim.reason == "more precise than the evidence", (text, claim.reason)
    # coarser than the evidence is fine
    assert _check("It was published at 12:32 UTC on 2026-09-29.", BYD).passed


def test_de12_table_and_prose_swaps_flagged() -> None:
    table = "| Field | 1211.HK | 0700.HK |\n|---|---|---|\n| Close | 75.6 | 75.6 |"
    check = _check(table, PAIR)
    assert check.failed == ["75.6"] and check.subject_mismatch == ["75.6"]
    assert guardrail.run_postcheck(table, PAIR).display_text.endswith("| 75.6 | 75.6[?] |")
    prose = _check("0700.HK closed at 75.6 while 1211.HK closed at 644.63.", PAIR)
    assert prose.subject_mismatch == ["75.6", "644.63"]
    assert [c.reason for c in prose.claims] == ["this close belongs to 1211.HK", "this close belongs to 0700.HK"]


# ---- subjects and fields --------------------------------------------------------


def test_subject_resolution_order() -> None:
    assert _check("1211.HK closed at 75.6.", PAIR).passed  # preceding mention
    assert _check("A close of 644.63 for 0700.HK.", PAIR).passed  # following mention
    assert not _check("A close of 75.6 for 0700.HK.", PAIR).passed
    assert _check("0700.HK had a quiet session.\nIts close was 644.63.", PAIR).passed  # paragraph
    assert not _check("0700.HK had a quiet session.\nIts close was 75.6.", PAIR).passed
    assert _check("0700.HK had a quiet session.\n\nThe close was 75.6.", PAIR).passed  # new paragraph: any
    assert _check("0700.HK and 1211.HK closed at 644.63 and 75.6, respectively.", PAIR).passed
    swapped = _check("0700.HK and 1211.HK closed at 75.6 and 644.63, respectively.", PAIR)
    assert swapped.subject_mismatch == ["75.6", "644.63"]


def test_subject_names_from_evidence() -> None:
    ledger = {**SESSION, **PAIR}  # watchlist names: Tencent, BYD, Apple
    assert _check("Tencent closed at 644.63.", ledger).passed
    assert _claim("Tencent closed at 75.6.", ledger, "75.6").reason == "this close belongs to 1211.HK"
    # an ambiguous first word maps to no subject
    rows = [*ledger["turn-0001/watchlist.list#1"], {"canonical_symbol": "0285.HK", "official_name": "BYD Electronic"}]
    ambiguous = {**ledger, "turn-0001/watchlist.list#1": rows}
    assert _claim("BYD closed at 644.63.", ambiguous, "644.63").subject is None


FIELD_CASES = [
    ("price", "pair", "1211.HK trades at 75.6.", "1211.HK trades at 75.9."),
    ("open", "pair", "1211.HK opened at 74.9.", "1211.HK opened at 75.6."),
    ("high", "pair", "1211.HK hit a high of 76.2.", "1211.HK hit a high of 74.5."),
    ("low", "pair", "For 1211.HK the day low was 74.5.", "For 1211.HK the day low was 76.2."),
    ("adjusted close", "pair", "The 1211.HK adjusted close was 75.6.", "The 1211.HK adjusted close was 74.9."),
    ("volume", "pair", "1211.HK volume was 18,982,584 shares.", "1211.HK volume was 18,982,580 shares."),
    ("volatility", "byd", "Volatility is 37.12%.", "Volatility is 38%."),
    ("drawdown", "byd", "The drawdown was 36.1%.", "The drawdown was 19.3%."),
    ("ROE", "fundamentals", "Apple's ROE is 1.45.", "Apple's ROE is 1.6."),
    ("net margin", "fundamentals", "The net margin is 24.9%.", "The net margin is 46.5%."),
    ("gross margin", "fundamentals", "The gross margin is 46.5%.", "The gross margin is 24.9%."),
    ("revenue growth", "fundamentals", "Revenue growth was 5.96%.", "Revenue growth was 7%."),
    ("P/E", "fundamentals", None, "Apple's P/E is 32."),
    ("sentiment", "byd", "A sentiment score of 0.71 was recorded.", "A sentiment score of 0.75 was recorded."),
    ("sessions", "byd", "The window spans 259 sessions.", "The window spans 260 sessions."),
    ("news count", "byd", "The feed returned 3 headlines.", "The feed returned 5 headlines."),
    ("symbol count", "session", "The watchlist holds 3 symbols.", "The watchlist holds 4 symbols."),
    ("gaps", "session", "There are 2 pending gaps.", "There are 3 pending gaps."),
    ("tokens", "session", "The budget is 64,000 tokens.", "The budget is 32,000 tokens."),
    ("API calls", "session", "Sync used 37 API calls today.", "Sync used 38 API calls today."),
    ("revenue", "fundamentals", "Revenue was $94.04 billion.", "Revenue was $90 billion."),
    ("net income", "fundamentals", "Net income was $23.43 billion.", "Net income was $30 billion."),
    ("gross profit", "fundamentals", "Gross profit was $43.7 billion.", "Gross profit was $40 billion."),
    ("equity", "fundamentals", "Equity stood at $66.8 billion.", "Equity stood at $70 billion."),
    ("price target", "pair", None, "The price target is 90."),
]


@pytest.mark.parametrize(("field_class", "ledger", "correct", "wrong"), FIELD_CASES)
def test_field_cues_per_class(field_class: str, ledger: str, correct: str | None, wrong: str) -> None:
    if correct is not None:
        check = _check(correct, LEDGERS[ledger])
        assert check.passed, (field_class, check.failed, [c.reason for c in check.claims])
    check = _check(wrong, LEDGERS[ledger])
    assert not check.passed, (field_class, wrong)


def test_unknown_evidence_keys_are_compatible() -> None:
    assert _check("The close was 309.0.", {"tool": {"level": 309.0}}).passed
    inert = {"turn-0001/fundamentals.summary#1": {"symbol": "AAPL.US", "coverage": {"quarters_expected": 8}}}
    assert not _check("Apple's P/E is 8.", inert).passed  # bookkeeping keys are typed, never data


def test_unavailable_field_reason() -> None:
    assert _claim("BYD's ROE is 12%.", BYD, "12").reason == "the tool reported ROE unavailable for 1211.HK"
    assert _claim("Apple's P/S is 7.", FUND, "7").reason == "no P/S evidence"


# ---- values ------------------------------------------------------------------------


def test_rounding_at_written_precision() -> None:
    for text in (
        "1211.HK closed at 76.", "1211.HK closed at 75.6.", "1211.HK closed at 75.60.",
        "Volatility is 37%.", "Volatility is 37.1%.", "Volatility is 37.12%.", "Volatility is 37.116%.",
        "Volatility is 0.37.", "Volatility is 0.371.", "Volatility is 0.3712.",
        "Volume was 18.98 million shares.", "Volume was 19 million shares.", "Volume was 18,982,584 shares.",
        "Volume was 19.0m shares.", "Volume was 18,983k shares.",
        "The drawdown was 3,609 bps.",
    ):
        check = _check(text, BYD)
        assert check.passed, (text, check.failed)
    for text in ("Revenue was $94 billion.", "Revenue was 94,036 million dollars.", "ROE was 1.45x."):
        assert _check(text, FUND).passed, text


def test_rounding_boundaries() -> None:
    exact_half = {"q": {"symbol": "1211.HK", "close": 436.65}}
    assert _check("1211.HK closed at 436.6.", exact_half).passed
    assert _check("1211.HK closed at 436.7.", exact_half).passed
    beyond = {"q": {"symbol": "1211.HK", "close": 436.6501}}
    assert not _check("1211.HK closed at 436.6.", beyond).passed
    close = {"q": {"symbol": "1211.HK", "close": 436.6}}
    assert _check("1211.HK closed at 437.", close).passed
    for value in ("438", "435", "436"):
        assert not _check(f"1211.HK closed at {value}.", close).passed, value
    assert not _check("Volume was 19,000,000 shares.", BYD).passed  # written in full: exact
    assert _check("Volume was 19 million shares.", BYD).passed


def test_sign_and_decline_words() -> None:
    for text in ("It fell 36.09% from its peak.", "A -36.09% drawdown.", "The drawdown was 36.09%."):
        assert _check(text, BYD).passed, text
    rose = _claim("It rose 36.09% from its peak.", BYD, "36.09")
    assert not rose.verified and rose.reason == "the tool's drawdown is a decline"
    fell = _claim("Revenue fell 6% year over year.", FUND, "6")
    assert not fell.verified and fell.reason == "the tool's revenue growth is a rise"


def test_duration_span_is_derived_not_misattributed() -> None:
    """TP-024 live finding (DE-15): a duration span must not inherit a nearby field cue.

    A live BYD session wrote "...a drawdown of -36.09% within the last 13
    months..."; the nearest preceding cue ("drawdown") claimed "13" across
    the intervening preposition, and the unmatched value failed with the
    misleading reason "differs from the tool's drawdown".
    """
    text = (
        "A volatility reading of 37.12% and a drawdown of -36.09% within the "
        "last 13 months describe a volatile name."
    )
    claim = _claim(text, BYD, "13")
    assert not claim.verified and claim.field == "drawdown"
    assert claim.reason == "derived value; only compute-tool results verify"
    weeks = _claim("The drawdown was -36.09% over the past 6 weeks.", BYD, "6")
    assert not weeks.verified and weeks.reason == "derived value; only compute-tool results verify"
    hyphen = _claim("A -36.09% drawdown over a 6-month span.", BYD, "6")
    assert not hyphen.verified and hyphen.reason == "derived value; only compute-tool results verify"


def test_currency_must_agree() -> None:
    usd = _claim("1211.HK closed at USD 75.6.", PAIR, "75.6")
    assert not usd.verified and usd.reason == "the tool reports close in HKD"
    assert _check("1211.HK closed at HKD75.6.", PAIR).passed
    assert _check("1211.HK closed at $75.6.", PAIR).passed  # a bare $ names no currency


def test_unfielded_claims_keep_v1_rules() -> None:
    value = {"tool": {"value": 100.0}}
    for token in ("101", "99", "100.5", "100.99"):
        assert not _check(f"the figure is {token}", value).passed, token
    pool = {"q": {"x": 24879.2402, "y": 0.4528}}
    assert _check("the figure 24,879.24 stands", pool).rounded == ["24879.24"]  # BD-012
    assert not _check("the figure 24,879 stands", pool).passed  # whole numbers round only with a field
    assert _check("about 45.28% of it", pool).passed  # BD-015, marker-gated
    assert not _check("about 45% of it", pool).passed


def test_free_text_digits_only_verify_quotes() -> None:
    quoted = 'A headline read "BYD sells 380,000 vehicles in September as overseas deliveries rise".'
    assert _check(quoted, BYD).passed
    assert _claim(quoted, BYD, "380,000").cls == "quoted"
    paraphrase = _claim('A headline said "BYD sold 380,000 cars last month".', BYD, "380,000")
    assert not paraphrase.verified and paraphrase.reason == "quoted text not found in the tool results"
    short = _claim('It said "380,000 vehicles" were sold.', BYD, "380,000")  # under three words
    assert not short.verified and short.reason == "appears only in tool text; quote it to cite it"


# ---- times -------------------------------------------------------------------------


def test_temporal_whole_parse() -> None:
    for text in (
        "It was published at 2026-09-29T12:32:02Z.",
        "It was published 20260929T123202Z.",
        "It was published on September 29, 2026 at 12:32 UTC.",
        "It was published at 20:32 HKT on 29 Sep 2026.",
        "It was published at 12:32:02 +00:00 on 2026-09-29.",
        "It was published at 12:32:02 on 2026-09-29.",
    ):
        check = _check(text, BYD)
        assert check.passed, (text, check.failed)
    assert not _check("It was published at 13:32 UTC on 2026-09-29.", BYD).passed


def test_temporal_precision_levels() -> None:
    for text in (
        "Prices were weak in 2026.", "The news came in Q3 2026.", "The news came in September 2026.",
        "The second headline ran on 2026-09-26.", "It ran at 2026-09-26 08:15:00 UTC.",
    ):
        assert _check(text, BYD).passed, text
    assert _claim("It ran on 2026-09-27.", BYD, "2026-09-27").reason == "no matching tool date or time"
    later = _claim("The close of 75.6 was set at 16:00 HKT on 2026-09-29.", BYD, "16:00 HKT")
    assert later.reason == "more precise than the evidence"  # the quote date has no time


def test_window_membership() -> None:
    for text in ("Volatility rose in November 2025.", "Volatility rose in Q4 2025.", "It was volatile in 2025.",
                 "Volatility rose in September 2025."):
        assert _check(text, BYD).passed, text
    assert not _check("Volatility rose in August 2025.", BYD).passed  # ends before the window opens
    assert not _check("Volatility rose in October 2026.", BYD).passed  # after the window
    assert not _check("Volatility spiked on 2025-11-14.", BYD).passed  # a day must be an evidence date
    assert _check("0700.HK rallied in November 2025.", PAIR).passed
    assert _check("Apple's growth window starts in June 2025.", FUND).passed


def test_de13_year_rules() -> None:
    for text in (
        "2025 was a volatile year.",
        "2025 saw a sharp drawdown.",
        "| Year | Close |\n|---|---|\n| 2025 | 75.6 |",
        "The volatility window runs from 2025 to 2026.",
        "Data covers 2025-2026.",
    ):
        check = _check(text, BYD)
        assert check.passed, (text, check.failed)
    assert _check("The stock rose from 2025 to 2026.", BYD).failed == ["2025", "2026"]
    assert _check("2025 shares were traded.", BYD).failed == ["2025"]
    assert _check("| Value | 2025 |", BYD).failed == ["2025"]
    assert _check("The window runs from 2025 to 2026 HKD.", BYD).failed == ["2025", "2026"]
    # a value word after the year keeps it a number, even under a "Year" label
    assert _check("| Year | 2026 HKD |", BYD).failed == ["2026"]


# ---- identifiers, counts, words ---------------------------------------------------


def test_tickers_are_identifiers() -> None:
    check = _check("9988.HK has no stored data yet.", BYD)
    assert check.passed and check.claims == []
    assert _check("Code 9988 has no stored data yet.", BYD).failed == ["9988"]


def test_counts_against_list_lengths() -> None:
    assert _check("The watchlist holds 3 symbols.", SESSION).passed
    assert not _check("The watchlist holds 4 symbols.", SESSION).passed
    assert _check("The feed returned 3 headlines.", BYD).passed
    assert not _check("The feed returned 5 headlines.", BYD).passed
    assert _check("There are 2 pending gaps.", SESSION).passed
    assert not _check("There are 3 pending gaps.", SESSION).passed


def test_number_words() -> None:
    assert _check("Volatility is about thirty-seven percent.", BYD).passed
    assert _claim("Volatility is about forty percent.", BYD, "forty percent").verified is False
    assert _check("The feed returned three headlines.", BYD).passed
    assert not _check("The feed returned five headlines.", BYD).passed
    assert _check("Revenue was ninety-four billion dollars.", FUND).passed
    for text in ("There are two reasons for caution.", "It is one of the largest makers."):
        assert _check(text, BYD).claims == [], text


def test_period_labels_stay_identifiers() -> None:
    check = _check("Q4 results are due; H1 guidance and FY2026 targets follow.", {})
    assert check.passed and check.claims == []
    assert _check("Q5 results are due.", {}).failed == ["5"]


# ---- marking, classification, fail-closed ------------------------------------------


def test_marking_by_claim_position() -> None:
    text = "1211.HK closed at 75.6. 0700.HK closed at 75.6."
    verdict = guardrail.run_postcheck(text, PAIR)
    assert verdict.display_text == "1211.HK closed at 75.6. 0700.HK closed at 75.6[?]."
    for text, expected in (
        ("The trough came on 2026-04-09.", "The trough came on 2026-04-09[?]."),
        ("Volatility is high since March 2024.", "Volatility is high since March 2024[?]."),
        ("Volatility is about forty percent.", "Volatility is about forty percent[?]."),
    ):
        shown = guardrail.run_postcheck(text, BYD).display_text
        assert shown == expected, shown
        assert shown.replace(MARK, "") == text


def _all_texts() -> list[tuple[str, object]]:
    texts = [(item["text"], LEDGERS[item["ledger"]]) for item in DEV["items"] + HELD_OUT["items"]]
    texts += [(case[2], LEDGERS[case[1]]) for case in FIELD_CASES if case[2]]
    texts += [(case[3], LEDGERS[case[1]]) for case in FIELD_CASES]
    return texts


def test_every_digit_is_classified() -> None:
    claims_module = importlib.import_module("stockinsider.agent.guardrail_claims")
    for text, ledger in _all_texts():
        scan = claims_module.scan_claims(text, ledger)
        spans = [(c.start, c.end) for c in scan.claims] + [(s, e) for s, e, _kind in scan.exempt]
        covered = [0] * len(text)
        for start, end in spans:
            for index in range(start, end):
                covered[index] += 1
        for index, char in enumerate(text):
            if char.isdigit():
                assert covered[index] == 1, (text, index, covered[index])


def test_fail_closed_guard_still_withholds(monkeypatch) -> None:
    real = guardrail.postcheck_numbers

    def misplaced(candidate, snapshot_values, specs=None):
        check = real(candidate, snapshot_values)
        claims = [c if c.verified else dataclasses.replace(c, start=0, end=len(c.raw)) for c in check.claims]
        return dataclasses.replace(check, claims=claims)

    monkeypatch.setattr(guardrail, "postcheck_numbers", misplaced)
    verdict = guardrail.run_postcheck("0700.HK closed at 75.6.", PAIR)
    assert verdict.quarantined is True and verdict.display_text == "data unavailable for: 75.6"


# ---- notice, record, /show ---------------------------------------------------------


def test_notice_record_and_show_carry_reasons(store, prompts_dir) -> None:
    from stockinsider.agent.repl import render_session

    engine = make_engine(
        store, [ChatOutcome(text="The close was 999 and the P/E is 18; also 777.", usage={})], prompts_dir
    )
    record = store.create(profile="standard")
    spy = Spy()
    outcome = engine.run_turn(
        record["session_id"], "q", profile="standard", render=spy.render, progress=spy.progress, stream_sink=spy.sink
    )
    assert outcome.displayed == "The close was 999[?] and the P/E is 18[?]; also 777[?]."
    notice = (
        "unverified (no close evidence; marked [?]): 999; "
        "unverified (no P/E evidence; marked [?]): 18; "
        "unverified (not found in this session's tool results; marked [?]): 777"
    )
    assert notice in spy.lines
    event = [e for e in store.read_events(record["session_id"]) if e["event"] == "assistant-message"][-1]
    assert event["unverified"] == ["999", "18", "777"]
    assert event["unverified_detail"] == [
        {"claim": "999", "class": "quantitative", "subject": None, "field": "close", "reason": "no close evidence"},
        {"claim": "18", "class": "quantitative", "subject": None, "field": "P/E", "reason": "no P/E evidence"},
        {"claim": "777", "class": "quantitative", "subject": None, "field": None,
         "reason": "not found in this session's tool results"},
    ]
    lines: list[str] = []
    render_session(store, record["session_id"], lines.append)
    assert "  unverified 18 - no P/E evidence" in lines
    assert "  unverified 777 - not found in this session's tool results" in lines


# ---- generated zero-tolerance battery ----------------------------------------------

_GENERATED = [
    ("{s} closed at {v}.", "close"),
    ("{s} opened at {v}.", "open"),
    ("{s} hit a high of {v}.", "high"),
    ("The {s} volume was {v} shares.", "volume"),
    ("{s}'s volatility is {v}%.", "volatility"),
    ("| Field | {s} |\n|---|---|\n| Close | {v} |", "close"),
]
_TRUTH = {
    ("1211.HK", "close"): 75.6, ("1211.HK", "open"): 74.9, ("1211.HK", "high"): 76.2,
    ("1211.HK", "volume"): 18982584.0, ("1211.HK", "volatility"): 37.11553760998695,
    ("0700.HK", "close"): 644.63, ("0700.HK", "open"): 640.0, ("0700.HK", "high"): 648.5,
    ("0700.HK", "volume"): 15230411.0, ("0700.HK", "volatility"): 28.41,
}


def _render(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def test_generated_zero_tolerance_battery() -> None:
    rng = random.Random(20261002)
    escapes, false_flags = [], []
    for _round in range(40):
        for template, field_class in _GENERATED:
            for subject in ("1211.HK", "0700.HK"):
                truth = _TRUTH[(subject, field_class)]
                decimals = 0 if field_class == "volume" else rng.choice([0, 1, 2])
                correct = template.format(s=subject, v=_render(truth, decimals))
                if not _check(correct, PAIR if field_class != "volatility" else {**PAIR, **BYD}).passed:
                    false_flags.append(correct)
                factor = rng.choice([-1, 1]) * rng.uniform(0.02, 0.5)
                fabricated = round(truth * (1 + factor), decimals)
                if abs(fabricated - truth) <= 0.5 * 10 ** (-decimals) + 1e-9:
                    continue
                text = template.format(s=subject, v=_render(fabricated, decimals))
                ledger = PAIR if field_class != "volatility" else {**PAIR, **BYD}
                if _check(text, ledger).passed:
                    escapes.append(text)
    assert escapes == [], escapes[:5]
    assert false_flags == [], false_flags[:5]


# ---- E-010 corpora ----------------------------------------------------------------


def _evaluate(items: list[dict]) -> dict[str, list]:
    """Per-claim labels against the engine: false flags, escapes, unlabeled flags."""
    found: dict[str, list] = {"correct": [], "wrong": [], "false_flags": [], "escapes": [], "extra_flags": []}
    for item in items:
        text = item["text"]
        claims = list(_check(text, LEDGERS[item["ledger"]]).claims)
        used: set[int] = set()
        position = 0
        for label in item["claims"]:
            start = text.find(label["text"], position)
            assert start >= 0, (item["id"], label["text"])
            position = start + len(label["text"])
            overlapping = [i for i, c in enumerate(claims) if c.start < position and c.end > start]
            used.update(overlapping)
            flagged = any(not claims[i].verified for i in overlapping)
            key = (item["id"], label["text"])
            if label["correct"]:
                found["correct"].append(key)
                if flagged:
                    found["false_flags"].append(key)
            else:
                found["wrong"].append(key)
                if not flagged:
                    found["escapes"].append(key)
        found["extra_flags"] += [(item["id"], c.raw) for i, c in enumerate(claims) if i not in used and not c.verified]
    return found


def test_e010_dev_corpus() -> None:
    result = _evaluate(DEV["items"])
    assert len(result["correct"]) + len(result["wrong"]) >= 40
    assert result["escapes"] == [] and result["false_flags"] == [] and result["extra_flags"] == []


#: Held-out claims the engine flags although they are labeled correct, pinned
#: by name (E-010 residuals). The field comes from the previous sentence
#: ("Tencent's drawdown ran ... Tencent lost 19%"); an unfielded whole-number
#: percent keeps the v1 rule (P2) and stays flagged.
HELD_OUT_RESIDUALS: set[tuple[str, str]] = {("H023", "19"), ("H023", "36")}

#: Held-out misattributions through company names the ledger cannot resolve
#: (no `official_name` in market tool results). Waived for TP-024 by the
#: owner (2026-10-02) and deferred to TP-025, where tools return names; DE-16.
#: The waiver covers exactly these claims: any other escape fails the test.
NAME_CLASS_WAIVER: set[tuple[str, str]] = {
    ("H020", "37.1"), ("H020", "28.4"), ("H022", "15.23"), ("H047", "46.49"), ("H047", "6"),
}


def test_e010_heldout_corpus() -> None:
    result = _evaluate(HELD_OUT["items"])
    assert set(result["escapes"]) == NAME_CLASS_WAIVER, sorted(set(result["escapes"]) ^ NAME_CLASS_WAIVER)
    precision = 1 - len(result["false_flags"]) / len(result["correct"])
    assert precision >= 0.90, precision
    assert set(result["false_flags"]) | set(result["extra_flags"]) == HELD_OUT_RESIDUALS, (
        sorted((set(result["false_flags"]) | set(result["extra_flags"])) ^ HELD_OUT_RESIDUALS)
    )


def test_marker_never_alters_text() -> None:
    for text, ledger in _all_texts():
        shown = guardrail.run_postcheck(text, ledger).display_text
        if MARK in shown:
            assert shown.replace(MARK, "") == text
        assert not re.search(r"\[\?\]\[\?\]", shown)
