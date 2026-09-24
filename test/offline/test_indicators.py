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
import math
from stockinsider.data.compute.indicators import (
    annualized_volatility,
    gross_margin,
    max_drawdown,
    net_margin,
    pb_ratio,
    pe_ratio,
    ps_ratio,
    roe,
    yoy_growth,
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


# ---- TP-013a: the deterministic indicator suite ---------------------------


def test_valuation_golden() -> None:
    # price 250.0; EPS = 20_000_000 / 10_000_000 = 2.0 -> PE 125.0
    pe = pe_ratio(250.0, 20_000_000.0, 10_000_000.0)
    assert pe["value"] == 125.0
    # book per share = 1_500_000_000 / 10_000_000 = 150 -> PB 5/3
    pb = pb_ratio(250.0, 1_500_000_000.0, 10_000_000.0)
    assert abs(pb["value"] - 250.0 / 150.0) < 1e-6
    # sales per share = 4_000_000_000 / 10_000_000 = 400 -> PS 0.625
    ps = ps_ratio(250.0, 4_000_000_000.0, 10_000_000.0)
    assert abs(ps["value"] - 0.625) < 1e-6
    for item in (pe, pb, ps):
        assert item["unit"] == "ratio"


def test_valuation_unavailable_explicit() -> None:
    assert "unavailable" in pe_ratio(None, 1.0, 1.0)
    assert "unavailable" in pe_ratio(250.0, None, 1.0)
    assert "unavailable" in pe_ratio(250.0, 1.0, 0.0)  # non-positive shares
    assert "unavailable" in pe_ratio(250.0, -5.0, 1.0)  # negative earnings: PE undefined
    assert "unavailable" in pb_ratio(250.0, -1.0, 1.0)  # negative book: PB undefined
    assert "unavailable" in ps_ratio(250.0, 1.0, None)


def test_profitability_golden() -> None:
    r = roe(2_000_000.0, 10_000_000.0)
    assert abs(r["value"] - 0.2) < 1e-6
    m = net_margin(2_000_000.0, 40_000_000.0)
    assert abs(m["value"] - 0.05) < 1e-6
    g = gross_margin(18_000_000.0, 40_000_000.0)
    assert abs(g["value"] - 0.45) < 1e-6
    assert "unavailable" in roe(None, 10.0)
    assert "unavailable" in net_margin(1.0, 0.0)  # zero revenue: explicit


def test_growth_golden_and_gaps() -> None:
    series = [
        ("2025-06-30", 100.0),
        ("2025-09-30", 110.0),
        ("2025-12-31", 105.0),
        ("2026-03-31", 120.0),
        ("2026-06-30", 132.0),
    ]
    result = yoy_growth(series)
    assert abs(result["value"] - 0.32) < 1e-6  # 132 vs 100
    assert result["window"] == {"from": "2025-06-30", "until": "2026-06-30"}
    short = yoy_growth(series[:4])
    assert "unavailable" in short
    negative_base = yoy_growth([("2025-06-30", -10.0)] + series[1:])
    assert "unavailable" in negative_base


def test_risk_golden() -> None:
    # constructed path: +1% twelve sessions, -2% twelve sessions (25 closes)
    closes = [100.0]
    for _ in range(12):
        closes.append(closes[-1] * 1.01)
    for _ in range(12):
        closes.append(closes[-1] * 0.98)
    bars = [{"date": f"2026-09-{i + 1:02d}", "close": c} for i, c in enumerate(closes)]
    vol = annualized_volatility(bars)
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    expected = math.sqrt(var) * math.sqrt(252)
    assert abs(vol["value"] - expected) < 1e-6
    # hand-computed anchor: std(12x ln1.01, 12x ln0.98) annualized
    assert abs(vol["value"] - 0.2444837) < 1e-3
    assert vol["window"]["sessions"] == 24
    assert vol["window"]["from"] == "2026-09-01" and vol["window"]["until"] == "2026-09-25"

    dd = max_drawdown(bars)
    # peak after the twelfth +1% day (100*1.01^12), trough at the end
    peak = closes[12]
    trough = closes[-1]
    assert abs(dd["value"] - (trough - peak) / peak) < 1e-6
    assert dd["window"]["peak_date"] == "2026-09-13"
    assert dd["window"]["trough_date"] == "2026-09-25"


def test_risk_insufficient_explicit() -> None:
    bars = [{"date": "2026-09-01", "close": 100.0}, {"date": "2026-09-02", "close": 101.0}]
    assert "unavailable" in annualized_volatility(bars)  # < 20 returns
    assert "unavailable" in max_drawdown(bars[:1])


def test_windows_carried() -> None:
    bars = [{"date": f"2026-08-{i + 1:02d}", "close": 100.0 + i} for i in range(25)]
    vol = annualized_volatility(bars)
    assert vol["window"]["from"] == "2026-08-01"
    assert vol["window"]["until"] == "2026-08-25"
    dd = max_drawdown(bars)
    assert "peak_date" in dd["window"] and "trough_date" in dd["window"]
