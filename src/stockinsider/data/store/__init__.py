"""Authoritative data store: SQLite + symbol map + watchlist.

Opened through `open_data_store` (data facade); the agent side reaches
this package only via agent/registry tools (blueprint §5).

Implements: REQ-SI-FR-004, REQ-SI-INV-004 (ADR-003)
"""

from __future__ import annotations

import sqlite3
from typing import Any

from stockinsider.data.store.db import SchemaVersionError, open_db
from stockinsider.data.store.resolver import (
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

    def run_sync(self) -> dict[str, Any]:
        """Execute one sync run (plan, budget, gaps, completeness) and report.

        Implements: REQ-SI-FR-001, REQ-SI-QA-003, REQ-SI-INV-003 (ADR-002)
        """
        from stockinsider.data.ingest.sync import SyncService

        return SyncService(self._conn).run().as_dict()

    def sync_status(self) -> dict[str, Any]:
        """Read-only sync status (budget, pending gaps, tracked symbols).

        Implements: REQ-SI-FR-001 (ADR-002)
        """
        from stockinsider.data.ingest.sync import sync_status

        return sync_status(self._conn)

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
