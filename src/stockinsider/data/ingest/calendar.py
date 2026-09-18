"""Trading calendars derived from benchmark index bars (D3 decision).

HK trading days are the dates present in HSI.IND bars; US days are the
dates present in GSPC.IND bars. Zero extra API surface, and the FR-001
completeness rule is self-consistent by construction: the calendar IS
the benchmark's own bar dates. Missing index bars raise an explicit
CalendarUnavailable — the sync service always backfills indices first.

Implements: REQ-SI-FR-001, REQ-SI-QA-003 (ADR-002)
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date, timedelta

CALENDAR_INDEX = {"HK": "HSI.IND", "US": "GSPC.IND"}


class CalendarUnavailable(RuntimeError):
    """No benchmark bars to derive a calendar from (explicit, fail-closed).

    Implements: REQ-SI-INV-003 (ADR-002)
    """


def trading_dates(conn: sqlite3.Connection, exchange: str, start: str, end: str) -> list[str]:
    """Expected trading dates for [start, end], ascending.

    Implements: REQ-SI-FR-001 (ADR-002)
    """
    symbol = CALENDAR_INDEX.get(exchange)
    if symbol is None:
        raise CalendarUnavailable(f"no calendar index mapped for exchange {exchange!r}")
    rows = conn.execute(
        """
        SELECT DISTINCT date FROM market_bars
        WHERE canonical_symbol = ? AND date BETWEEN ? AND ?
        ORDER BY date
        """,
        (symbol, start, end),
    ).fetchall()
    dates = [row["date"] for row in rows]
    if not dates:
        raise CalendarUnavailable(
            f"no {symbol} bars stored in [{start}, {end}]; sync benchmark indices first (they run at plan priority 1)"
        )
    return dates


def _next_day(day: str) -> str:
    """One calendar day forward (gap contiguity test).

    Implements: REQ-SI-FR-001 (ADR-002)
    """
    y, m, d = (int(part) for part in day.split("-"))
    return (_date(y, m, d) + timedelta(days=1)).isoformat()


def missing_ranges(stored: set[str], expected: list[str]) -> list[tuple[str, str]]:
    """Contiguous missing-date runs as (from, to) tuples.

    Implements: REQ-SI-FR-001 (ADR-002)
    """

    missing = [day for day in expected if day not in stored]
    ranges: list[tuple[str, str]] = []
    run_from: str | None = None
    previous: str | None = None
    for day in missing:
        if run_from is None:
            run_from = day
        elif previous is not None and _next_day(previous) != day:
            ranges.append((run_from, previous))
            run_from = day
        previous = day
    if run_from is not None and previous is not None:
        ranges.append((run_from, previous))
    return ranges
