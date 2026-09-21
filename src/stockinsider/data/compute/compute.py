"""Deterministic computation: the ONLY home of market-data arithmetic (FR-006).

Born in TP-010 with the display-move primitives; the full indicator
suite (valuations, profitability, growth, risk) lands in TP-013.
Everything here is a pure function over plain values — golden-fixture
tested to 1e-6; no I/O, no LLM, no exceptions for empty inputs other
than explicit InvalidInput (fail-closed, INV-003).

Implements: REQ-SI-FR-006 (ADR-001)
"""

from __future__ import annotations

from typing import Any, Sequence

_EPSILON = 1e-12


class InvalidInput(RuntimeError):
    """Explicit computation refusal (missing/zero base, bad shape).

    Implements: REQ-SI-INV-003 (ADR-001)
    """


def pct_change(previous: float, current: float) -> float:
    """Percent change from previous to current; explicit on zero base.

    Implements: REQ-SI-FR-006 (ADR-001)
    """
    if abs(previous) < _EPSILON:
        raise InvalidInput("pct_change: previous value is zero; ratio undefined (INV-003)")
    return (current - previous) / previous * 100.0


def max_abs_daily_move(bars: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """Largest |close-to-close % move| in a bar sequence (ascending).

    Implements: REQ-SI-FR-006 (ADR-001)
    """
    best: dict[str, Any] | None = None
    for previous, current in zip(bars, bars[1:]):
        try:
            move = abs(pct_change(previous["close"], current["close"]))
        except InvalidInput:
            continue  # zero-base day: skipped, never fabricated (INV-003)
        if best is None or move > best["abs_pct"]:
            best = {"date": current["date"], "abs_pct": move}
    return best


def move_vs(bars: Sequence[dict[str, Any]], sessions: int) -> dict[str, Any] | None:
    """Percent move of the last close vs `sessions` closes earlier.

    Implements: REQ-SI-FR-006 (ADR-001)
    """
    if len(bars) < sessions + 1:
        return None
    base = bars[-sessions - 1]
    last = bars[-1]
    try:
        return {"from_date": base["date"], "date": last["date"], "pct": pct_change(base["close"], last["close"])}
    except InvalidInput:
        return None


def period_over_period(series: Sequence[tuple[str, float]]) -> dict[str, Any] | None:
    """Latest-over-previous change of a dated series (ascending by date).

    Implements: REQ-SI-FR-006 (ADR-001)
    """
    if len(series) < 2:
        return None
    (prev_date, prev_value), (last_date, last_value) = series[-2], series[-1]
    try:
        return {
            "period": last_date,
            "previous": prev_date,
            "pct": pct_change(prev_value, last_value),
        }
    except InvalidInput:
        return None


def format_compact(value: float) -> str:
    """Human-scale rendering (K/M/B) for display; arithmetic stays here (FR-006).

    Implements: REQ-SI-FR-006 (ADR-001)
    """
    magnitude = abs(value)
    for divisor, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if magnitude >= divisor:
            return f"{value / divisor:.2f}{suffix}"
    return f"{value:.2f}"
