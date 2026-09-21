"""Offline tests for data/compute primitives: golden values (TP-010, FR-006).

Implements: REQ-SI-FR-006 (ADR-001)
"""

import pytest

from stockinsider.data.compute import (
    InvalidInput,
    format_compact,
    max_abs_daily_move,
    move_vs,
    pct_change,
    period_over_period,
)


def test_pct_change_golden() -> None:
    assert pct_change(100.0, 110.0) == pytest.approx(10.0, abs=1e-6)
    assert pct_change(50.0, 49.5) == pytest.approx(-1.0, abs=1e-6)
    with pytest.raises(InvalidInput):
        pct_change(0.0, 10.0)


def test_max_abs_daily_move_and_window() -> None:
    bars = [
        {"date": "2026-09-01", "close": 100.0},
        {"date": "2026-09-02", "close": 103.0},  # +3%
        {"date": "2026-09-03", "close": 101.0},  # -1.94%
        {"date": "2026-09-04", "close": 104.0},
    ]
    best = max_abs_daily_move(bars)
    assert best is not None and best["date"] == "2026-09-02"
    assert best["abs_pct"] == pytest.approx(3.0, abs=1e-6)
    versus = move_vs(bars, 3)
    assert versus is not None
    assert versus["pct"] == pytest.approx(4.0, abs=1e-6)
    assert move_vs(bars, 10) is None  # not enough sessions -> explicit None


def test_period_over_period_golden() -> None:
    series = [("2026-03-31", 100.0), ("2026-06-30", 125.0)]
    pop = period_over_period(series)
    assert pop is not None and pop["pct"] == pytest.approx(25.0, abs=1e-6)
    assert period_over_period([("2026-03-31", 100.0)]) is None


def test_format_compact() -> None:
    assert format_compact(161_000_000_000.0) == "161.00B"
    assert format_compact(12_300_000.0) == "12.30M"
    assert format_compact(-1234.0) == "-1.23K"
    assert format_compact(12.5) == "12.50"
