"""TP-020 suite: partial-date citations (BD-026).

A live BYD turn was quarantined as "data unavailable for: 2025" because
the model wrote an evidence date at month precision ("since September
2025") while the evidence carries dates only as full dates. Month-years
and bare years written as time references now pass when the evidence
calendar supports them (docs/test-plans/TP-020.md). The bypass
direction is pinned as hard as the fix: a number that merely equals an
evidence year, in a value frame, is still a numeric claim.

Implements: REQ-SI-INV-001, REQ-SI-QA-001 (ADR-006 Am9; TP-020)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stockinsider.agent.guardrail import postcheck_numbers
from stockinsider.agent.loop import TurnEngine, TurnOutcome
from stockinsider.agent.providers import ChatOutcome
from stockinsider.agent.registry import Registry, register_market_tools
from stockinsider.agent.session import SessionStore
from stockinsider.data.store import DataStore
from stockinsider.data.store.db import open_db
from test_streaming import ScriptedProvider

#: The live shape: market.indicators risk section for 1211.HK, a year of
#: history, so the window start and the drawdown peak fall in 2025.
EVIDENCE = {
    "turn-0002/market.indicators#4": {
        "symbol": "1211.HK",
        "as_of": "2026-09-29",
        "risk": {
            "volatility": {
                "metric": "volatility",
                "value": 0.4123,
                "unit": "fraction",
                "window": {"from": "2025-09-25", "until": "2026-09-29", "sessions": 259},
            },
            "max_drawdown": {
                "metric": "max_drawdown",
                "value": -0.3512,
                "unit": "fraction",
                "window": {"peak_date": "2025-10-03", "trough_date": "2026-04-08"},
            },
        },
    }
}
NEWS_POOL = {
    "turn-0001/news.recent#1": {
        "items": [{"seendate": "20260923T183300Z", "title": "BYD expands overseas plants"}]
    }
}


# ---- month-years and ISO year-months --------------------------------------------


def test_month_year_supported_by_evidence_passes() -> None:
    for text in (
        "Volatility covers the sessions since September 2025.",
        "Volatility covers the sessions since Sep. 2025.",
        "Volatility covers the sessions since September, 2025.",
        "The drawdown began at a peak in Oct 2025.",
        "The trough came in April 2026.",
    ):
        check = postcheck_numbers(text, EVIDENCE)
        assert check.passed, (text, check.failed)
        assert check.calendar, text


def test_iso_year_month_supported_by_evidence_passes() -> None:
    check = postcheck_numbers("Window: 2025-09 to 2026-09.", EVIDENCE)
    assert check.passed, check.failed
    assert check.calendar == ["2025-09", "2026-09"]


# ---- bare years in a temporal frame ----------------------------------------------


def test_time_referenced_bare_years_pass() -> None:
    for text in (
        "The window opens in 2025.",
        "Volatility is measured since 2025.",
        "The window opens in late 2025.",
        "Volatility is measured since mid-2025.",
        "The peak came by the end of 2025.",
        "Data as of 2026.",
        "Q4 2025 and FY 2025 sit inside the window.",
        "The window starts in fiscal 2025.",
        "The drawdown started at the 2025 peak.",
        "It fell from 2025's high.",
        "The 2026 H1 trough is the low point.",
    ):
        check = postcheck_numbers(text, EVIDENCE)
        assert check.passed, (text, check.failed)


def test_year_ranges_inherit_the_frame() -> None:
    for text in (
        "The window runs from late 2025 to 2026.",
        "Volatility is measured during 2025-2026.",
        "Volatility covers the 2025–2026 window.",
        "The window runs from September 2025 to 2026.",
    ):
        check = postcheck_numbers(text, EVIDENCE)
        assert check.passed, (text, check.failed)
    # "from ... to" frames values as often as times: no frame, no allowance
    assert postcheck_numbers("The stock rose from 2025 to 2026.", EVIDENCE).failed == ["2025", "2026"]
    # a value word on one member cancels the whole range
    assert postcheck_numbers("It traded late 2025 to 2026 HKD.", EVIDENCE).failed == ["2025", "2026"]


# ---- negatives: what must still fail ---------------------------------------------


def test_partial_dates_absent_from_evidence_fail() -> None:
    cases = {
        "Volatility is measured since March 2025.": ["2025"],  # year present, month absent
        "Volatility is measured since August 2025.": ["2025"],  # neighbouring month
        "The peak came in 2024.": ["2024"],
        "The trough came in late 2027.": ["2027"],
    }
    for text, failed in cases.items():
        check = postcheck_numbers(text, EVIDENCE)
        assert check.failed == failed, (text, check.failed)
    iso = postcheck_numbers("Window opens 2024-09.", EVIDENCE)
    assert not iso.passed and "2024" in iso.failed


def test_year_valued_numbers_stay_numeric_claims() -> None:
    """The evidence holds 2026 dates; a VALUE equal to 2026 is not a year."""
    for text in (
        "The stock closed at 2026.",
        "Volume was 2026 shares.",
        "It trades at HKD2026.",
        "A 2026% move.",
        "Last close: 2026",
        "| close | 2026 |",
        "In 2026 HKD terms it is cheap.",
        "Holdings in 2026.HK rose.",
        "It rose 2026 points.",
    ):
        check = postcheck_numbers(text, EVIDENCE)
        assert not check.passed, text
        assert "2026" in check.failed, (text, check.failed)
        assert check.calendar == [], text


def test_full_dates_keep_day_precision() -> None:
    assert postcheck_numbers("The window opened on 25 September 2025.", EVIDENCE).passed
    wrong_day = postcheck_numbers("The window opened on 26 September 2025.", EVIDENCE)
    assert wrong_day.failed == ["20250926"]  # September 2025 is an evidence month; the day is not
    absent = postcheck_numbers("It appeared on September 24, 2026.", NEWS_POOL)
    assert absent.failed == ["20260924"]


def test_evidence_calendar_reads_dates_not_numbers() -> None:
    numbers_only = {"turn-0001/market.quote#1": {"volume": 202509, "close": 2025.5}}
    check = postcheck_numbers("Volatility is measured since September 2025.", numbers_only)
    assert check.failed == ["2025"]  # a number shaped like a month makes no month citable
    assert postcheck_numbers("The article ran in September 2026.", NEWS_POOL).passed
    assert postcheck_numbers("The article ran in August 2026.", NEWS_POOL).failed == ["2026"]


def test_cue_less_year_stays_a_number() -> None:
    """Fail-closed default (DE-13): no temporal frame, no allowance."""
    assert postcheck_numbers("2025 was a volatile year.", EVIDENCE).failed == ["2025"]
    assert postcheck_numbers("| Year | 2025 |", EVIDENCE).failed == ["2025"]


def test_calendar_hits_are_audited() -> None:
    check = postcheck_numbers("Measured since September 2025, through late 2026.", EVIDENCE)
    assert check.passed
    assert check.calendar == ["September 2025", "2026"]
    assert check.matched == [] and check.rounded == []


# ---- end to end: the live turn shape through the real tool ---------------------

IDENTITY = """---
version: 1
artifact: identity
---

# Test identity

You are a test analyst.
"""

#: 22 bars: window 2025-09-25..2026-09-29, peak 2025-10-03, trough 2026-04-08
BARS = [
    ("2025-09-25", 100.0),
    ("2025-10-03", 120.0),
    ("2025-11-14", 110.0),
    ("2025-12-19", 105.0),
    ("2026-01-16", 98.0),
    ("2026-02-13", 95.0),
    ("2026-03-13", 90.0),
    ("2026-04-08", 80.0),
    ("2026-05-15", 85.0),
    ("2026-05-29", 86.0),
    ("2026-06-12", 87.0),
    ("2026-06-26", 88.0),
    ("2026-07-10", 89.0),
    ("2026-07-24", 90.0),
    ("2026-08-07", 91.0),
    ("2026-08-21", 92.0),
    ("2026-09-04", 93.0),
    ("2026-09-11", 94.0),
    ("2026-09-18", 95.0),
    ("2026-09-25", 96.0),
    ("2026-09-28", 97.0),
    ("2026-09-29", 98.0),
]


@pytest.fixture()
def engine_parts(tmp_path) -> tuple[SessionStore, Registry, Path]:
    conn = open_db(tmp_path / "market.sqlite")
    with conn:
        conn.execute(
            "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type,"
            " aliases, verified, source, resolved_at)"
            " VALUES ('1211.HK', 'HKEX', 'BYD Company Ltd', 'stock', '[]', 1, 'eodhd',"
            " '2026-09-01T00:00:00+00:00')"
        )
        for day, close in BARS:
            conn.execute(
                "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close,"
                " volume, currency, source, fetched_at)"
                " VALUES ('1211.HK', ?, ?, ?, ?, ?, 0, 'HKD', 'eodhd', '2026-09-30')",
                (day, close, close, close, close),
            )
    registry = Registry()
    register_market_tools(registry, DataStore(conn))
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "identity.md").write_text(IDENTITY, encoding="utf-8")
    return SessionStore(root=tmp_path / "sessions"), registry, prompts


def _run_byd_turn(engine_parts: tuple[SessionStore, Registry, Path], answer: str) -> tuple[TurnOutcome, list[str]]:
    store, registry, prompts = engine_parts
    call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "market.indicators", "arguments": json.dumps({"symbol": "1211.HK"})},
    }
    provider = ScriptedProvider([ChatOutcome(tool_calls=[call]), ChatOutcome(text=answer)])
    engine = TurnEngine(store, registry, provider, prompts_dir=prompts)
    record = store.create(profile="standard")
    lines: list[str] = []
    outcome = engine.run_turn(
        record["session_id"],
        "give me info about BYD",
        profile="standard",
        render=lines.append,
        progress=lines.append,
        stream_sink=lambda _piece: None,
    )
    return outcome, lines


def test_bd026_live_shape_passes_in_the_loop(engine_parts) -> None:
    answer = (
        "For 1211.HK, volatility covers the sessions since September 2025, and the "
        "drawdown ran from the 2025 peak in October 2025 to a trough in April 2026."
    )
    outcome, lines = _run_byd_turn(engine_parts, answer)
    assert any("market.indicators … ok (computed)" in line for line in lines)
    assert outcome.quarantined is False
    assert outcome.displayed == answer
    assert any("post-check: pass" in line for line in lines)


def test_bd026_unsupported_month_still_quarantines_in_the_loop(engine_parts) -> None:
    outcome, lines = _run_byd_turn(engine_parts, "For 1211.HK, volatility covers the sessions since March 2024.")
    assert outcome.quarantined is True
    assert outcome.displayed == "data unavailable for: 2024"
    assert any("post-check: failed" in line for line in lines)
