"""Authoritative data store: SQLite + symbol map + watchlist.

Opened through `open_data_store` (data facade); the agent side reaches
this package only via agent/registry tools (blueprint §5).

Implements: REQ-SI-FR-004, REQ-SI-INV-004 (ADR-003)
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable

from stockinsider.data.store.db import SchemaVersionError, open_db
from datetime import datetime, timedelta, timezone

from stockinsider.data.store.resolver import (
    Resolution,
    ResolverUnavailable,
    SymbolResolver,
    seed_benchmarks,
)
from stockinsider.data.store.watchlist import (
    ACTIVE_CAP,
    WatchlistError,
    WatchlistService,
)

__all__ = [
    "ACTIVE_CAP",
    "DataStore",
    "ResolverUnavailable",
    "SchemaVersionError",
    "WatchlistError",
    "WatchlistService",
    "open_data_store",
]


class DataStore:
    """One open database with its services (single composition point).

    Implements: REQ-SI-FR-004 (ADR-003)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.watchlist = WatchlistService(conn)
        self.resolver = SymbolResolver()

    def record(self, resolution: Any) -> None:
        """Persist a verified resolution into the symbol map (INV-004 gate input).

        Implements: REQ-SI-FR-004 (ADR-003)
        """
        from stockinsider.data.store.resolver import record_resolution

        record_resolution(self._conn, resolution)

    def news_knn(
        self,
        query_vector: list[float],
        model_id: str,
        *,
        k: int = 5,
        bucket: str | None = None,
    ) -> list[dict[str, Any]]:
        """Top-k nearest news rows via sqlite-vec (fail-closed; ADR-003).

        Implements: REQ-SI-FR-007 (ADR-003)
        """
        from stockinsider.data.store.vector import knn

        hits = knn(self._conn, model_id, query_vector, k=k, bucket=bucket)
        return [
            {
                "news_id": hit.news_id,
                "title_raw": hit.title,
                "url": hit.url,
                "domain": hit.domain,
                "seendate": hit.seendate,
                "bucket": hit.bucket,
                "distance": hit.distance,
            }
            for hit in hits
        ]

    def run_sync(self, progress: "Callable[[str], None] | None" = None) -> dict[str, Any]:
        """Execute one sync run (plan, budget, gaps, completeness) and report.

        The optional progress callback is pure observability for the
        CLI surface (TP-015); it never alters execution.

        Implements: REQ-SI-FR-001, REQ-SI-QA-003, REQ-SI-INV-003 (ADR-002)
        """
        from stockinsider.data.ingest.sync import SyncService

        return SyncService(self._conn).run(progress=progress).as_dict()

    def sync_status(self) -> dict[str, Any]:
        """Read-only sync status (budget, pending gaps, tracked symbols).

        Implements: REQ-SI-FR-001 (ADR-002)
        """
        from stockinsider.data.ingest.sync import sync_status

        return sync_status(self._conn)

    @property
    def conn(self) -> sqlite3.Connection:
        """The underlying connection (read tools and services; single store).

        Implements: REQ-SI-FR-005 (ADR-003)
        """
        return self._conn

    def info_lines(self, symbol: str) -> list[str]:
        """Render the deterministic FR-005 snapshot lines for a symbol.

        Implements: REQ-SI-FR-005 (ADR-002)
        """
        from stockinsider.data.store.info import render_info

        return render_info(self._conn, symbol)

    def market_quote(self, symbol: str) -> "dict[str, Any] | None":
        """Latest stored EOD bar for a symbol (None if absent).

        Implements: REQ-SI-FR-005 (ADR-005, ADR-002; gamma restoration)
        """
        row = self._conn.execute(
            "SELECT date, open, high, low, close, adjusted_close, volume, currency "
            "FROM market_bars WHERE canonical_symbol = ? ORDER BY date DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return dict(row) if row is not None else None

    def fundamentals_coverage(self, symbol: str) -> dict[str, Any]:
        """FR-002 coverage snapshot ONLY (M8 honesty record, TP-017).

        The current vendor plan lacks the fundamentals feed, so this
        returns the coverage ratio, not a rich summary; per-section
        unavailable fields are explicit inside. A fuller summary is
        future work gated on the feed.

        Implements: REQ-SI-FR-002 (ADR-005, ADR-002; gamma restoration)
        """
        from stockinsider.data.ingest.fundamentals import coverage

        return coverage(self._conn, symbol)

    def fundamentals_summary(self, symbol: str) -> dict[str, Any]:
        """Honest fundamentals summary for the registry tool (M8, TP-018).

        The tool named fundamentals.summary used to return the coverage
        ratio alone, while its description promised "latest stored
        fundamentals" — the model read the name, claimed stored data,
        and passed every check. This facade returns the coverage grid
        AND whatever rows are actually stored, with an explicit
        unavailable marker when the feed has never been ingested
        (INV-003: the absence is stated, never implied away).

        Implements: REQ-SI-FR-002 (ADR-005, ADR-002; TP-018 PR-3)
        """
        import json as _json

        from stockinsider.data.ingest.fundamentals import coverage

        cov = coverage(self._conn, symbol)
        rows = self._conn.execute(
            "SELECT period_end, statement_type, data FROM fundamentals "
            "WHERE canonical_symbol = ? ORDER BY period_end DESC LIMIT 4",
            (symbol,),
        ).fetchall()
        stored: list[dict[str, Any]] = []
        for row in rows:
            try:
                data = _json.loads(row["data"])
            except (ValueError, TypeError):
                data = {"parse_error": "stored payload is not valid JSON (INV-003)"}
            stored.append({"period_end": row["period_end"], "statement_type": row["statement_type"], "data": data})
        return {
            "symbol": symbol,
            "coverage": cov,
            "stored": stored,
            "stored_unavailable_reason": (
                None
                if stored
                else (
                    "no fundamentals rows stored for this symbol: the fundamentals "
                    "data feed is not in the current vendor plan (explicit, not omitted)"
                )
            ),
        }

    def news_recent_rows(self, symbol: str, k: int) -> list[dict[str, Any]]:
        """Latest k stored news rows for a symbol bucket, newest first.

        Raw storage read; sanitization is the caller's egress duty
        (SEC-002 layer one stays on the agent side).

        Implements: REQ-SI-FR-007 (ADR-005; gamma restoration)
        """
        rows = self._conn.execute(
            "SELECT title, url_raw, domain, published_at, source, sentiment"
            " FROM news WHERE symbol = ? ORDER BY published_at DESC LIMIT ?",
            (symbol, k),
        ).fetchall()
        return [dict(row) for row in rows]

    def market_indicators_snapshot(self, symbol: str) -> dict[str, Any]:
        """Deterministic indicator snapshot (profitability/growth/risk).

        All market-data arithmetic lives on the data side (FR-006);
        the registry surface only relays the result.

        Implements: REQ-SI-FR-006 (ADR-005, ADR-002; gamma restoration)
        """
        import json as _json

        from stockinsider.data.compute.indicators import (
            annualized_volatility,
            gross_margin,
            max_drawdown,
            net_margin,
            roe,
            yoy_growth,
        )

        # M7 (TP-017): risk metrics price the ADJUSTED series — raw
        # closes double-count splits/dividends as volatility.
        price_row = self._conn.execute(
            "SELECT date, COALESCE(adjusted_close, close) AS close FROM market_bars"
            " WHERE canonical_symbol = ? ORDER BY date DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if price_row is None:
            raise KeyError(f"{symbol}: no stored market data (sync first; INV-003)")
        bars = self._conn.execute(
            "SELECT date, COALESCE(adjusted_close, close) AS close FROM market_bars"
            " WHERE canonical_symbol = ? ORDER BY date DESC LIMIT 260",
            (symbol,),
        ).fetchall()
        income_rows = self._conn.execute(
            "SELECT period_end, data FROM fundamentals WHERE canonical_symbol = ?"
            " AND statement_type = 'income' ORDER BY period_end",
            (symbol,),
        ).fetchall()
        balance_rows = self._conn.execute(
            "SELECT period_end, data FROM fundamentals WHERE canonical_symbol = ?"
            " AND statement_type = 'balance' ORDER BY period_end DESC LIMIT 1",
            (symbol,),
        ).fetchall()

        def _field(row: Any, key: str) -> float | None:
            try:
                value = _json.loads(row["data"]).get(key)
            except (ValueError, TypeError):
                return None
            return float(value) if isinstance(value, (int, float)) else None

        revenue_series = [
            (str(row["period_end"]), _field(row, "totalRevenue") or 0.0)
            for row in income_rows
            if _field(row, "totalRevenue") is not None
        ]
        latest_income = income_rows[-1] if income_rows else None
        latest_revenue = _field(latest_income, "totalRevenue") if latest_income else None
        latest_net_income = _field(latest_income, "netIncome") if latest_income else None
        latest_equity = _field(balance_rows[0], "totalStockholdersEquity") if balance_rows else None
        return {
            "symbol": symbol,
            "as_of": price_row["date"],
            "valuation": {
                "note": (
                    "share count is not captured by the fundamentals adapter; "
                    "per-share ratios unavailable until it is (INV-003)"
                )
            },
            "profitability": {
                "roe": roe(latest_net_income, latest_equity),
                "net_margin": net_margin(latest_net_income, latest_revenue),
                "gross_margin": gross_margin(None, latest_revenue),
            },
            "growth": {
                "revenue_yoy": yoy_growth(revenue_series),
                "earnings_yoy": {"unavailable": "quarterly net-income series not assembled in this snapshot"},
            },
            "risk": {
                "volatility": annualized_volatility([dict(bar) for bar in bars]),
                "max_drawdown": max_drawdown([dict(bar) for bar in bars]),
            },
        }

    def verify_symbol(self, canonical: str, adapter: "Any | None" = None) -> "Resolution | None":
        """Direct-symbol verification via one budgeted EOD fetch (BD-017).

        The vendor search endpoint does not index HK listings; a
        query shaped like a canonical symbol goes straight to the
        EOD seam. One bar proves existence (fail-closed: no data,
        no candidate). The display name is honestly unverified.
        Costs one budgeted call regardless of outcome (the vendor
        saw the request). Adapter injection is the test seam.

        Implements: REQ-SI-FR-004, REQ-SI-INV-004, REQ-SI-INV-003 (ADR-002, BD-017)
        """
        from stockinsider.data.ingest.budget import CallBudget
        from stockinsider.data.ingest.market import EodhdMarketAdapter

        adapter = adapter if adapter is not None else EodhdMarketAdapter()
        if not adapter.is_live():
            raise ResolverUnavailable(
                "direct verification is not configured: set EODHD_API_KEY "
                "(real environment variable or the local env file) (INV-003)"
            )
        budget = CallBudget(self._conn)
        if not budget.try_spend(1):
            raise ResolverUnavailable(
                "direct verification refused: daily call budget exhausted; retry after the budget resets (INV-003)"
            )
        suffix = canonical.rsplit(".", 1)[1].upper()
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=30)
        bars = adapter.fetch_eod(canonical, start.isoformat(), end.isoformat())
        if not bars:
            return None
        return Resolution(
            canonical_symbol=canonical,
            exchange=suffix,
            official_name=(
                f"{canonical} (name unverified - vendor search does not index this exchange; verify before adding)"
            ),
            asset_type="unverified",
        )

    def close(self) -> None:
        """Close the underlying connection.

        Implements: REQ-SI-FR-004 (ADR-003)
        """
        self._conn.close()


def open_data_store(root: "str | None" = None) -> DataStore:
    """Open (and migrate once) the store; seed benchmark indices.

    Implements: REQ-SI-FR-001, REQ-SI-FR-004 (ADR-003)
    """
    conn = open_db(root)
    seed_benchmarks(conn)
    return DataStore(conn)
