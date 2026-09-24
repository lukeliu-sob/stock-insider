"""Deterministic indicator suite (FR-006): valuation, profitability, growth, risk.

Pure functions over stored rows — the LLM never performs arithmetic
on market data (the static arithmetic gate confines it here). Every
result carries its data window; every gap is an explicit unavailable
entry, never a zero substitution (INV-003). Hand-computed golden
fixtures pin outputs at 1e-6 (test_indicators.py).

Implements: REQ-SI-FR-006, REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

import math
from typing import Any, Sequence

#: Trading days per year for annualization (HK/US convention blend).
TRADING_DAYS_PER_YEAR = 252

#: Minimum data points for volatility to be meaningful.
MIN_VOLATILITY_POINTS = 20


def _unavailable(metric: str, reason: str) -> dict[str, Any]:
    """One explicit unavailable entry (INV-003: no zero substitution)."""
    return {"metric": metric, "unavailable": reason}


def _ratio(metric: str, numerator: float | None, denominator: float | None, window: dict[str, str]) -> dict[str, Any]:
    """A ratio with fail-closed semantics: missing or non-positive parts are explicit."""
    if numerator is None or denominator is None:
        return _unavailable(metric, "input value missing from stored data")
    if denominator <= 0:
        return _unavailable(metric, f"denominator not positive ({denominator!r})")
    return {
        "metric": metric,
        "value": numerator / denominator,
        "unit": "ratio",
        "window": window,
    }


# ---- valuation ----------------------------------------------------------------


def pe_ratio(price: float | None, net_income: float | None, shares: float | None) -> dict[str, Any]:
    """Price over trailing earnings (per-share basis).

    Implements: REQ-SI-FR-006 (ADR-002)
    """
    if price is None:
        return _unavailable("pe", "no stored price")
    if net_income is None or shares is None or shares <= 0:
        return _unavailable("pe", "earnings or share count unavailable/non-positive")
    if net_income <= 0:
        return _unavailable("pe", f"net income not positive ({net_income!r}); P/E undefined")
    return {
        "metric": "pe",
        "value": price / (net_income / shares),
        "unit": "ratio",
        "window": {},
    }


def pb_ratio(price: float | None, equity: float | None, shares: float | None) -> dict[str, Any]:
    """Price over book value per share.

    Implements: REQ-SI-FR-006 (ADR-002)
    """
    if price is None:
        return _unavailable("pb", "no stored price")
    if equity is None or shares is None or shares <= 0:
        return _unavailable("pb", "book equity or share count unavailable/non-positive")
    if equity <= 0:
        return _unavailable("pb", f"book equity not positive ({equity!r}); P/B undefined")
    return {
        "metric": "pb",
        "value": price / (equity / shares),
        "unit": "ratio",
        "window": {},
    }


def ps_ratio(price: float | None, revenue: float | None, shares: float | None) -> dict[str, Any]:
    """Price over trailing sales per share.

    Implements: REQ-SI-FR-006 (ADR-002)
    """
    if price is None:
        return _unavailable("ps", "no stored price")
    if revenue is None or shares is None or shares <= 0:
        return _unavailable("ps", "revenue or share count unavailable/non-positive")
    return {
        "metric": "ps",
        "value": price / (revenue / shares),
        "unit": "ratio",
        "window": {},
    }


# ---- profitability --------------------------------------------------------------


def roe(net_income: float | None, equity: float | None) -> dict[str, Any]:
    """Return on equity (trailing).

    Implements: REQ-SI-FR-006 (ADR-002)
    """
    return _ratio("roe", net_income, equity, {})


def net_margin(net_income: float | None, revenue: float | None) -> dict[str, Any]:
    """Net income over revenue (trailing).

    Implements: REQ-SI-FR-006 (ADR-002)
    """
    return _ratio("net_margin", net_income, revenue, {})


def gross_margin(gross_profit: float | None, revenue: float | None) -> dict[str, Any]:
    """Gross profit over revenue (trailing).

    Implements: REQ-SI-FR-006 (ADR-002)
    """
    return _ratio("gross_margin", gross_profit, revenue, {})


# ---- growth ----------------------------------------------------------------------


def yoy_growth(series: Sequence[tuple[str, float]]) -> dict[str, Any]:
    """Latest value versus the same period one year earlier.

    ``series`` is (period_end, value) ordered; the comparison pairs
    periods four quarters apart when quarterly, else falls back to
    the closest ~365-day match. Insufficient coverage is explicit.

    Implements: REQ-SI-FR-006 (ADR-002)
    """
    if len(series) < 5:  # need latest + year-ago with quarter spacing
        return _unavailable("yoy_growth", f"insufficient history ({len(series)} periods; need 5+)")
    ordered = sorted(series, key=lambda item: item[0])
    latest_period, latest_value = ordered[-1]
    year_ago = ordered[-5]
    prior_value = year_ago[1]
    if prior_value <= 0:
        return _unavailable("yoy_growth", f"year-ago value not positive ({prior_value!r})")
    growth = (latest_value - prior_value) / abs(prior_value)
    return {
        "metric": "yoy_growth",
        "value": growth,
        "unit": "fraction",
        "window": {"from": year_ago[0], "until": latest_period},
    }


# ---- risk --------------------------------------------------------------------------


def annualized_volatility(bars: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Annualized std of daily log returns (sqrt-252 convention).

    Implements: REQ-SI-FR-006 (ADR-002)
    """
    ordered = sorted(bars, key=lambda bar: bar["date"])
    closes = [float(bar["close"]) for bar in ordered if float(bar.get("close") or 0) > 0]
    if len(closes) < MIN_VOLATILITY_POINTS + 1:
        return _unavailable(
            "volatility", f"insufficient history ({len(closes) - 1} returns; need {MIN_VOLATILITY_POINTS})"
        )
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return {
        "metric": "volatility",
        "value": math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR),
        "unit": "fraction",
        "window": {"from": ordered[0]["date"], "until": ordered[-1]["date"], "sessions": len(returns)},
    }


def max_drawdown(bars: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Largest peak-to-trough decline of the close series.

    Implements: REQ-SI-FR-006 (ADR-002)
    """
    ordered = sorted(bars, key=lambda bar: bar["date"])
    closes = [(bar["date"], float(bar["close"])) for bar in ordered if float(bar.get("close") or 0) > 0]
    if len(closes) < 2:
        return _unavailable("max_drawdown", "insufficient history (need 2+ closes)")
    peak_date, peak = closes[0]
    trough_date, trough = closes[0]
    best = 0.0
    best_window = {"peak_date": peak_date, "trough_date": trough_date}
    for date, close in closes:
        if close > peak:
            peak_date, peak = date, close
        drawdown = (close - peak) / peak if peak > 0 else 0.0
        if drawdown < best:
            best = drawdown
            best_window = {"peak_date": peak_date, "trough_date": date}
    return {
        "metric": "max_drawdown",
        "value": best,
        "unit": "fraction",
        "window": best_window,
    }
