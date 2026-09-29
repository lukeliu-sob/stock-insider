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
                "direct verification refused: daily call budget exhausted; "
                "retry after the budget resets (INV-003)"
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
                f"{canonical} (name unverified - vendor search does not index "
                "this exchange; verify before adding)"
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
