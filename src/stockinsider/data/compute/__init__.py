"""Deterministic computation: indicators, event study, statistics.

The ONLY module tree where market-data arithmetic happens (FR-006;
static gate enforced). Pure functions, golden-fixture tested.

Implements: REQ-SI-FR-006 (ADR-001)
"""

from __future__ import annotations

from stockinsider.data.compute.compute import (
    PERFORMANCE_WINDOWS,
    InvalidInput,
    format_compact,
    max_abs_daily_move,
    move_vs,
    pct_change,
    period_over_period,
    period_performance,
)

__all__ = [
    "PERFORMANCE_WINDOWS",
    "InvalidInput",
    "format_compact",
    "max_abs_daily_move",
    "move_vs",
    "pct_change",
    "period_over_period",
    "period_performance",
]
