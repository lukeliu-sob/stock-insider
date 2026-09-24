"""Sync service: plan, execute under budget, report (fail-closed).

Plan priority: (1) benchmark indices missing bars -> 5y backfill;
(2) the sync_gaps queue (watch-add enqueues land here); (3) active
watchlist incrementals (cursor -> today). After execution, a
completeness pass compares stored dates against the index-derived
calendar and enqueues newly found gaps (repaired by the NEXT sync —
FR-001 "next sync re-fetches"). Every item ends ok / failed / deferred
with an explicit detail; budget numbers ride the report (INV-003).

Implements: REQ-SI-FR-001, REQ-SI-QA-003, REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from stockinsider.data.ingest.budget import CallBudget
from stockinsider.data.ingest.calendar import CalendarUnavailable, missing_ranges, trading_dates
from stockinsider.data.ingest.http import Transport
from stockinsider.data.ingest.fundamentals import (
    CALL_COST as FUNDAMENTALS_COST,
    EodhdFundamentalsAdapter,
    FundamentalsNotInPlan,
)
from stockinsider.data.ingest.news import GdeltNewsAdapter, news_status, run_news_sync
from stockinsider.data.ingest.market import (
    EodhdMarketAdapter,
    InvalidMarketData,
    MarketKeyMissing,
    store_bars,
)

from stockinsider.data.store.resolver import BENCHMARK_INDICES

BACKFILL_DAYS = 5 * 365
MARKET_TRACK = "market:{symbol}"
FUND_TRACK = "fundamentals:{symbol}"
FUND_ACCESS_TRACK = "fundamentals-access"
#: Staleness rule: refetch when the newest stored quarter is older than
#: ~a quarter (95 days) behind the newest market bar. No calendar API.
FUND_STALENESS_DAYS = 95


@dataclass
class ItemResult:
    """One plan item's outcome (explicit, human-readable).

    Implements: REQ-SI-INV-003 (ADR-002)
    """

    symbol: str
    action: str  # backfill | incremental | gap-repair
    status: str  # ok | failed | deferred
    detail: str


@dataclass
class SyncReport:
    """The run's full report (INV-003 visibility).

    Implements: REQ-SI-INV-003 (ADR-002)
    """

    ran_at: str
    results: list[ItemResult] = field(default_factory=list)
    calls_used: int = 0
    calls_remaining: int = 0
    calls_cap: int = 0
    news: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """Render for tool/CLI surfaces.

        Implements: REQ-SI-FR-001 (ADR-002)
        """
        return {
            "ran_at": self.ran_at,
            "results": [vars(item) | {} for item in self.results],
            "news": self.news,
            "calls": {
                "used": self.calls_used,
                "remaining": self.calls_remaining,
                "cap": self.calls_cap,
            },
            "counts": {
                "ok": sum(1 for i in self.results if i.status == "ok"),
                "failed": sum(1 for i in self.results if i.status == "failed"),
                "deferred": sum(1 for i in self.results if i.status == "deferred"),
            },
        }


def _exchange_of(symbol: str) -> str:
    return symbol.rsplit(".", 1)[-1]


def _calendar_exchange(symbol: str) -> str:
    """Which benchmark calendar governs this symbol (HK vs US)."""
    if symbol.endswith(".HK") or symbol in ("HSI.INDX", "HSTECH.INDX"):
        return "HK"
    return "US"


class SyncService:
    """Plan-and-execute one sync run under the call budget.

    Implements: REQ-SI-FR-001, REQ-SI-QA-003 (ADR-002)
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        adapter: EodhdMarketAdapter | None = None,
        budget: CallBudget | None = None,
        transport: Transport | None = None,
        news_enabled: bool = True,
    ) -> None:
        self._conn = conn
        self._budget = budget if budget is not None else CallBudget(conn)
        self._adapter = adapter if adapter is not None else EodhdMarketAdapter(transport=transport)
        self._fund_adapter = EodhdFundamentalsAdapter(transport=transport)
        self._news_enabled = news_enabled
        self._transport = transport

    # -- helpers ----------------------------------------------------------

    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _window(self) -> tuple[str, str]:
        today = datetime.now(timezone.utc).date()
        return (today - timedelta(days=BACKFILL_DAYS)).isoformat(), today.isoformat()

    def _cursor(self, symbol: str) -> str | None:
        row = self._conn.execute(
            "SELECT cursor FROM sync_state WHERE track = ?", (MARKET_TRACK.format(symbol=symbol),)
        ).fetchone()
        return row["cursor"] if row else None

    def _set_cursor(self, symbol: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO sync_state (track, cursor, last_run_at, last_status, calls_today, calls_date)
                VALUES (?, ?, ?, 'ok', 0, NULL)
                ON CONFLICT(track) DO UPDATE SET
                    cursor = excluded.cursor, last_run_at = excluded.last_run_at,
                    last_status = excluded.last_status
                """,
                (MARKET_TRACK.format(symbol=symbol), value, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )

    def _fundamentals_enabled(self) -> bool:
        """True unless a recorded plan denial stands (re-probe via env override)."""
        import os

        if os.environ.get("EODHD_FUNDAMENTALS") == "1":
            return True
        row = self._conn.execute(
            "SELECT last_status FROM sync_state WHERE track = ?", (FUND_ACCESS_TRACK,)
        ).fetchone()
        return row is None or row["last_status"] != "denied"

    def _fundamentals_stale(self, symbol: str) -> bool:
        """True when statements are absent or lag the newest bar by a quarter."""
        bar = self._conn.execute(
            "SELECT MAX(date) AS d FROM market_bars WHERE canonical_symbol = ?", (symbol,)
        ).fetchone()
        newest_bar = bar["d"] if bar else None
        if newest_bar is None:
            return False  # no market data yet: fundamentals wait for the market track
        row = self._conn.execute(
            "SELECT MAX(period_end) AS p FROM fundamentals WHERE canonical_symbol = ?", (symbol,)
        ).fetchone()
        if row is None or row["p"] is None:
            return True
        from datetime import date as _date, timedelta

        y, m, d = (int(part) for part in newest_bar.split("-"))
        cutoff = (_date(y, m, d) - timedelta(days=FUND_STALENESS_DAYS)).isoformat()
        return row["p"] < cutoff

    def _has_bars(self, symbol: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM market_bars WHERE canonical_symbol = ? LIMIT 1", (symbol,)).fetchone()
        return row is not None

    def _execute(self, item: tuple[str, str, str, str], report: SyncReport) -> ItemResult:
        """Fetch+store one item under budget; every failure explicit."""
        symbol, action, from_date, to_date = item
        cost = FUNDAMENTALS_COST if action == "fundamentals" else 1
        if not self._budget.try_spend(cost):
            return ItemResult(
                symbol, action, "deferred",
                f"daily call budget exhausted (needs {cost}); runs next sync",
            )
        if action == "fundamentals":
            return self._execute_fundamentals(symbol)
        try:
            rows = self._adapter.fetch_eod(symbol, from_date, to_date)
            stored = store_bars(self._conn, symbol, rows)
            last_date = rows[-1]["date"] if rows else to_date
            previous = self._cursor(symbol)
            new_cursor = max(previous, last_date) if previous else last_date  # never regress
            self._set_cursor(symbol, new_cursor)
            if action == "gap-repair":
                with self._conn:
                    self._conn.execute(
                        "UPDATE sync_gaps SET resolved_at = ? WHERE canonical_symbol = ? "
                        "AND from_date = ? AND to_date = ? AND resolved_at IS NULL",
                        (datetime.now(timezone.utc).isoformat(timespec="seconds"), symbol, from_date, to_date),
                    )
            return ItemResult(symbol, action, "ok", f"{stored} bars stored; data through {last_date}")
        except (InvalidMarketData, MarketKeyMissing) as exc:
            return ItemResult(symbol, action, "failed", str(exc))
        except Exception as exc:  # noqa: BLE001 — classified transports arrive as TransportError
            kind = getattr(exc, "kind", type(exc).__name__)
            return ItemResult(symbol, action, "failed", f"[{kind}] {exc}")

    def _execute_fundamentals(self, symbol: str) -> ItemResult:
        """One fundamentals fetch; plan denial is recorded and skipped after."""
        try:
            outcome = self._fund_adapter.fetch_and_store(self._conn, symbol)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO sync_state (track, cursor, last_run_at, last_status) "
                    "VALUES (?, (SELECT MAX(period_end) FROM fundamentals WHERE canonical_symbol = ?), ?, 'ok') "
                    "ON CONFLICT(track) DO UPDATE SET cursor = excluded.cursor, "
                    "last_run_at = excluded.last_run_at, last_status = excluded.last_status",
                    (
                        FUND_TRACK.format(symbol=symbol),
                        symbol,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    ),
                )
            return ItemResult(
                symbol, "fundamentals", "ok",
                (
                    f"{outcome['statements']} statement rows stored; "
                    f"profile {'updated' if outcome['profile'] else 'absent'}"
                ),
            )
        except FundamentalsNotInPlan as exc:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO sync_state (track, last_run_at, last_status) VALUES (?, ?, 'denied') "
                    "ON CONFLICT(track) DO UPDATE SET last_status = 'denied', last_run_at = excluded.last_run_at",
                    (FUND_ACCESS_TRACK, datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
            return ItemResult(symbol, "fundamentals", "failed", str(exc))
        except Exception as exc:  # noqa: BLE001 — surfaced per-item, run continues (INV-003)
            kind = getattr(exc, "kind", type(exc).__name__)
            return ItemResult(symbol, "fundamentals", "failed", f"[{kind}] {exc}")

    # -- planning ---------------------------------------------------------

    def _plan(self) -> list[tuple[str, str, str, str]]:
        """(symbol, action, from, to) in priority order."""
        start, today = self._window()
        plan: list[tuple[str, str, str, str]] = []
        for entry in BENCHMARK_INDICES:
            symbol = entry["canonical_symbol"]
            if not self._has_bars(symbol):
                plan.append((symbol, "backfill", start, today))
        gap_rows = self._conn.execute(
            "SELECT canonical_symbol, from_date, to_date FROM sync_gaps WHERE resolved_at IS NULL ORDER BY detected_at"
        ).fetchall()
        for row in gap_rows:
            plan.append((row["canonical_symbol"], "gap-repair", row["from_date"], row["to_date"]))
        active = self._conn.execute(
            "SELECT canonical_symbol FROM watchlist WHERE status = 'active' ORDER BY canonical_symbol"
        ).fetchall()
        for row in active:
            symbol = row["canonical_symbol"]
            cursor = self._cursor(symbol)
            if cursor is None:
                plan.append((symbol, "backfill", start, today))
            elif cursor < today:
                plan.append((symbol, "incremental", cursor, today))
        if self._fundamentals_enabled():
            for row in active:
                symbol = row["canonical_symbol"]
                if self._fundamentals_stale(symbol):
                    plan.append((symbol, "fundamentals", "", today))
        return plan

    def _completeness_pass(self, report: SyncReport) -> None:
        """Compare stored dates vs the index calendar; enqueue new gaps."""
        start, today = self._window()
        for symbol in self._tracked_symbols():
            exchange = _calendar_exchange(symbol)
            try:
                expected = trading_dates(self._conn, exchange, start, today)
            except CalendarUnavailable as exc:
                report.results.append(ItemResult(symbol, "completeness", "failed", str(exc)))
                continue
            stored = self._stored_in_window(symbol, start, today)
            for from_date, to_date in missing_ranges(stored, expected):
                self._enqueue_gap(symbol, from_date, to_date)

    def _enqueue_gap(self, symbol: str, from_date: str, to_date: str) -> None:
        """Record a detected gap for the next run's priority 2."""
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO sync_gaps (canonical_symbol, from_date, to_date, detected_at)
                VALUES (?, ?, ?, ?)
                """,
                (symbol, from_date, to_date, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )

    # -- entry ------------------------------------------------------------

    def _enqueue_detected_gaps(self) -> None:
        """Pre-execution gap detection: enqueue before planning (FR-001a).

        Deletions or out-of-band losses since the last run land in the
        gap queue in time for THIS run's plan. Calendar-unavailable is
        expected on a fresh database (indices not yet backfilled) and
        is silently skipped here — the post-execution pass reports it.
        """
        start, today = self._window()
        for symbol in self._tracked_symbols():
            try:
                expected = trading_dates(self._conn, _calendar_exchange(symbol), start, today)
            except CalendarUnavailable:
                continue
            stored = self._stored_in_window(symbol, start, today)
            for from_date, to_date in missing_ranges(stored, expected):
                self._enqueue_gap(symbol, from_date, to_date)

    def _tracked_symbols(self) -> list[str]:
        symbols = [
            row["canonical_symbol"]
            for row in self._conn.execute("SELECT canonical_symbol FROM watchlist WHERE status = 'active'").fetchall()
        ]
        symbols += [e["canonical_symbol"] for e in BENCHMARK_INDICES]
        return symbols

    def _stored_in_window(self, symbol: str, start: str, today: str) -> set[str]:
        return {
            row["date"]
            for row in self._conn.execute(
                "SELECT date FROM market_bars WHERE canonical_symbol = ? AND date BETWEEN ? AND ?",
                (symbol, start, today),
            ).fetchall()
        }

    def run(self) -> SyncReport:
        """Execute one sync run; the report is the sole output surface.

        Implements: REQ-SI-FR-001, REQ-SI-QA-003, REQ-SI-INV-003 (ADR-002)
        """
        report = SyncReport(ran_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        used_before = self._budget.used_today()
        self._enqueue_detected_gaps()  # deletions since last run enter THIS run's plan
        for item in self._plan():
            report.results.append(self._execute(item, report))
        self._completeness_pass(report)
        report.calls_used = self._budget.used_today() - used_before
        report.calls_remaining = self._budget.remaining()
        report.calls_cap = self._budget.remaining() + self._budget.used_today()
        # News track (TP-011b): after the market track, isolated — a news
        # failure never fails the market report (design §8).
        if self._news_enabled:
            try:
                report.news = run_news_sync(
                    self._conn, adapter=GdeltNewsAdapter(transport=self._transport)
                )
            except Exception as exc:  # explicit isolation boundary
                report.news = {"failed": f"news track aborted: {exc}"}
        return report


def sync_status(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read-only sync status: budget, pending gaps, tracked symbols.

    Implements: REQ-SI-FR-001 (ADR-002)
    """
    budget = CallBudget(conn)
    pending = conn.execute(
        "SELECT canonical_symbol, from_date, to_date FROM sync_gaps WHERE resolved_at IS NULL"
    ).fetchall()
    active = conn.execute("SELECT COUNT(*) AS n FROM watchlist WHERE status = 'active'").fetchone()["n"]
    return {
        "budget": {
            "used": budget.used_today(),
            "remaining": budget.remaining(),
            "cap": budget.used_today() + budget.remaining(),
        },
        "pending_gaps": [dict(row) for row in pending],
        "active_symbols": int(active),
        "last_run": conn.execute(
            "SELECT last_run_at FROM sync_state WHERE track LIKE 'market:%' ORDER BY last_run_at DESC LIMIT 1"
        ).fetchone(),
        "news": news_status(conn),
    }
