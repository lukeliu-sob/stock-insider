"""Stored-data freshness against the current date (TP-047, ADR-002 Am3).

The trading calendar is derived from stored benchmark bars (calendar.py),
so it cannot say that a newer session exists. Freshness therefore uses
weekdays and a per-exchange availability time: the expected session is
the latest weekday whose end-of-day bar is reliably at the vendor by now.
A symbol is behind when its newest bar is older than that session AND
its market track has not run since the session became available - a sync
on a holiday finds nothing new, and the check stays quiet until the next
weekday instead of re-firing on every start.

Implements: REQ-SI-FR-028, REQ-SI-FR-001, REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from stockinsider.data.ingest.sync import MARKET_TRACK, _calendar_exchange
from stockinsider.data.store.resolver import BENCHMARK_INDICES

#: When a session's EOD bar is reliably at the vendor, in UTC: the close plus
#: a margin. HK closes 16:00 HKT (08:00 UTC); US closes 16:00 ET (20:00 or
#: 21:00 UTC with daylight saving), so 23:00 covers both offsets.
AVAILABLE_AFTER_UTC = {"HK": time(10, 0), "US": time(23, 0)}


def available_at(exchange: str, session: date) -> datetime:
    """The UTC instant from which `session`'s bar is expected at the vendor.

    Implements: REQ-SI-FR-028 (ADR-002)
    """
    return datetime.combine(session, AVAILABLE_AFTER_UTC[exchange], tzinfo=timezone.utc)


def expected_session(exchange: str, now: datetime) -> date:
    """The latest weekday whose bar is available at `now` (weekends skipped).

    Implements: REQ-SI-FR-028 (ADR-002)
    """
    day = now.astimezone(timezone.utc).date()
    while day.weekday() >= 5 or available_at(exchange, day) > now:
        day -= timedelta(days=1)
    return day


def _tracked(conn: sqlite3.Connection) -> list[str]:
    symbols = [entry["canonical_symbol"] for entry in BENCHMARK_INDICES]
    rows = conn.execute(
        "SELECT canonical_symbol FROM watchlist WHERE status = 'active' ORDER BY canonical_symbol"
    ).fetchall()
    return symbols + [row["canonical_symbol"] for row in rows if row["canonical_symbol"] not in symbols]


def behind(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict[str, Any]]:
    """Tracked symbols whose stored bars lag the expected session.

    Each row: symbol, exchange, newest stored bar (or None), expected session.

    Implements: REQ-SI-FR-028, REQ-SI-INV-003 (ADR-002)
    """
    now = now or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for symbol in _tracked(conn):
        exchange = _calendar_exchange(symbol)
        expected = expected_session(exchange, now)
        newest = conn.execute(
            "SELECT MAX(date) AS d FROM market_bars WHERE canonical_symbol = ?", (symbol,)
        ).fetchone()["d"]
        if newest is not None and newest >= expected.isoformat():
            continue
        run = conn.execute(
            "SELECT last_run_at FROM sync_state WHERE track = ?", (MARKET_TRACK.format(symbol=symbol),)
        ).fetchone()
        last_run = run["last_run_at"] if run is not None else None
        if last_run is not None and datetime.fromisoformat(last_run) >= available_at(exchange, expected):
            continue  # synced since the session became available: nothing newer exists (holiday)
        rows.append({"symbol": symbol, "exchange": exchange, "newest": newest, "expected": expected.isoformat()})
    return rows
