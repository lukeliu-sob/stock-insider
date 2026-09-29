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
from time import monotonic
from typing import Any, Callable

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
#: Fourth-audit high finding (TP-018b): a gap that returns zero bars
#: three times in a row is confirmed no-data (pre-listing suspension,
#: vendor holes) and closes with resolution='no-data' instead of
#: retrying forever and starving the daily budget (INV-003: the
#: absence is recorded, never silently re-queued).
MAX_EMPTY_ATTEMPTS = 3
#: Gap-repair may consume at most half the daily call cap per run;
#: the rest stays available to incremental updates so a long gap
#: queue can never starve the rest of the watchlist (fourth audit).
GAP_BUDGET_SHARE = 0.5
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
        row = self._conn.execute("SELECT last_status FROM sync_state WHERE track = ?", (FUND_ACCESS_TRACK,)).fetchone()
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

    def _detection_start(self, symbol: str, window_start: str) -> "str | None":
        """Earliest date worth gap-detecting for this symbol (or None: skip).

        Fourth-audit fix (TP-018b): the window start clips to the symbol's
        own earliest stored bar. Dates BEFORE a listing were detected as
        ~170 weekly gap segments that can never be filled (the vendor
        returns nothing pre-listing); with zero-bar gaps now staying open,
        those segments starved the whole daily budget. A symbol with no
        bars yet is skipped entirely - its backfill populates history and
        the NEXT run detects real gaps from the true first bar.

        Implements: REQ-SI-FR-001, REQ-SI-INV-003 (ADR-002; TP-018b)
        """
        row = self._conn.execute(
            "SELECT MIN(date) AS d FROM market_bars WHERE canonical_symbol = ?", (symbol,)
        ).fetchone()
        earliest = row["d"] if row else None
        if earliest is None:
            return None
        return max(window_start, earliest)

    def _has_bars(self, symbol: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM market_bars WHERE canonical_symbol = ? LIMIT 1", (symbol,)).fetchone()
        return row is not None

    def _execute(self, item: tuple[str, str, str, str], report: SyncReport) -> ItemResult:
        """Fetch+store one item under budget; every failure explicit."""
        symbol, action, from_date, to_date = item
        cost = FUNDAMENTALS_COST if action == "fundamentals" else 1
        if not self._budget.try_spend(cost):
            return ItemResult(
                symbol,
                action,
                "deferred",
                f"daily call budget exhausted (needs {cost}); runs next sync",
            )
        if action == "fundamentals":
            return self._execute_fundamentals(symbol)
        try:
            rows = self._adapter.fetch_eod(symbol, from_date, to_date)
            stored = store_bars(self._conn, symbol, rows)
            if not rows and action == "gap-repair":
                # low-4 (TP-018) + fourth-audit high finding (TP-018b):
                # an empty fetch proves nothing. The old path marked the
                # gap resolved anyway (zero-data-as-fixed, INV-003); the
                # naive fix kept it open forever, letting unfillable gaps
                # (pre-listing, suspension, vendor holes) eat the whole
                # daily budget. Now: attempts are counted, and after
                # MAX_EMPTY_ATTEMPTS the gap CLOSES as confirmed
                # no-data - recorded, not silently re-queued nor faked.
                with self._conn:
                    self._conn.execute(
                        "UPDATE sync_gaps SET empty_attempts = empty_attempts + 1 "
                        "WHERE canonical_symbol = ? AND from_date = ? AND to_date = ? "
                        "AND resolved_at IS NULL",
                        (symbol, from_date, to_date),
                    )
                    row = self._conn.execute(
                        "SELECT empty_attempts FROM sync_gaps "
                        "WHERE canonical_symbol = ? AND from_date = ? AND to_date = ?",
                        (symbol, from_date, to_date),
                    ).fetchone()
                attempts = row["empty_attempts"] if row else 1
                if attempts >= MAX_EMPTY_ATTEMPTS:
                    with self._conn:
                        self._conn.execute(
                            "UPDATE sync_gaps SET resolved_at = ?, resolution = 'no-data' "
                            "WHERE canonical_symbol = ? AND from_date = ? AND to_date = ? "
                            "AND resolved_at IS NULL",
                            (
                                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                symbol,
                                from_date,
                                to_date,
                            ),
                        )
                    return ItemResult(
                        symbol,
                        action,
                        "failed",
                        f"0 bars for {from_date}..{to_date} after {attempts} attempts; "
                        f"gap closed as confirmed no-data (INV-003)",
                    )
                return ItemResult(
                    symbol,
                    action,
                    "failed",
                    f"0 bars returned for {from_date}..{to_date}; retry scheduled "
                    f"({attempts}/{MAX_EMPTY_ATTEMPTS} attempts, cursor unchanged)",
                )
            if not rows:
                # backfill/incremental over a range with no trading data
                # (weekend, holiday): nothing to store, but the cursor
                # advances - the completeness pass re-detects genuinely
                # missing weekdays as explicit gaps (the safety net that
                # makes cursor advancement honest here).
                last_date = to_date
            else:
                last_date = rows[-1]["date"]
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
                symbol,
                "fundamentals",
                "ok",
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
            detect_from = self._detection_start(symbol, start)
            if detect_from is None:
                continue
            exchange = _calendar_exchange(symbol)
            try:
                expected = trading_dates(self._conn, exchange, detect_from, today)
            except CalendarUnavailable as exc:
                report.results.append(ItemResult(symbol, "completeness", "failed", str(exc)))
                continue
            stored = self._stored_in_window(symbol, detect_from, today)
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
            detect_from = self._detection_start(symbol, start)
            if detect_from is None:
                continue
            try:
                expected = trading_dates(self._conn, _calendar_exchange(symbol), detect_from, today)
            except CalendarUnavailable:
                continue
            stored = self._stored_in_window(symbol, detect_from, today)
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

    def run(self, progress: "Callable[[str], None] | None" = None) -> SyncReport:
        """Execute one sync run; the report is the sole output surface.

        The optional progress callback receives one human-readable
        line per plan item and track boundary as work completes
        (pure observability; it never alters execution) (TP-015).

        Implements: REQ-SI-FR-001, REQ-SI-QA-003, REQ-SI-INV-003 (ADR-002)
        """
        emit = progress if progress is not None else (lambda _line: None)
        started = monotonic()
        report = SyncReport(ran_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        used_before = self._budget.used_today()
        self._enqueue_detected_gaps()  # deletions since last run enter THIS run's plan
        plan = self._plan()
        emit(f"plan: {len(plan)} market item(s) (gaps detected first, then incrementals)")
        # Fourth-audit fix (TP-018b): gap-repair may consume at most half
        # the daily cap per run; the remainder always stays available to
        # incremental updates, so a long unfillable gap queue can never
        # starve the rest of the watchlist.
        gap_quota = max(1, int((self._budget.remaining() + self._budget.used_today()) * GAP_BUDGET_SHARE))
        gap_spent = 0
        for item in plan:
            if item[1] == "gap-repair" and gap_spent >= gap_quota:
                deferred = ItemResult(
                    item[0], item[1], "deferred",
                    f"gap-repair budget share ({gap_quota} calls/run) exhausted; "
                    "incremental updates proceed first",
                )
                report.results.append(deferred)
                emit(f"market {deferred.symbol} {deferred.action}: {deferred.status} ({deferred.detail})")
                continue
            t0 = monotonic()
            before = self._budget.used_today()
            result = self._execute(item, report)
            report.results.append(result)
            if item[1] == "gap-repair":
                gap_spent += self._budget.used_today() - before
            emit(f"market {result.symbol} {result.action}: {result.status} ({result.detail}) +{monotonic() - t0:.1f}s")
        self._completeness_pass(report)
        report.calls_used = self._budget.used_today() - used_before
        report.calls_remaining = self._budget.remaining()
        report.calls_cap = self._budget.remaining() + self._budget.used_today()
        # News track (TP-011b): after the market track, isolated — a news
        # failure never fails the market report (design §8).
        if self._news_enabled:
            report.news = {}
            emit("news/gdelt: start")
            try:  # GDELT: macro groups (and symbols while throttled)
                report.news["gdelt"] = run_news_sync(
                    self._conn,
                    adapter=GdeltNewsAdapter(transport=self._transport),
                    progress=progress,
                )
            except Exception as exc:  # explicit isolation boundary
                report.news["gdelt"] = {"failed": f"gdelt track aborted: {exc}"}
                emit(f"news/gdelt: aborted ({exc})")
            emit("news/eodhd: start")
            try:  # EODHD: primary symbol-scoped source (TP-014)
                from stockinsider.data.ingest.eodnews import run_eodhd_news_sync

                report.news["eodhd"] = run_eodhd_news_sync(self._conn, progress=progress)
            except Exception as exc:  # explicit isolation boundary
                report.news["eodhd"] = {"failed": f"eodhd track aborted: {exc}"}
                emit(f"news/eodhd: aborted ({exc})")
        emit(f"sync tracks complete +{monotonic() - started:.1f}s")
        return report


def _last_run_row(conn: sqlite3.Connection) -> "dict[str, Any] | None":
    """The newest market-track cursor as a plain dict (H5: a raw sqlite Row
    is not JSON-serializable and crashed the tool-result relay).

    Implements: REQ-SI-INV-003 (ADR-002; TP-017 PR-1)
    """
    row = conn.execute(
        "SELECT last_run_at FROM sync_state WHERE track LIKE 'market:%' ORDER BY last_run_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row is not None else None


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
        "last_run": _last_run_row(conn),
        "news": news_status(conn),
    }
