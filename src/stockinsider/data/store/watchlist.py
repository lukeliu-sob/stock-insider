"""Watchlist service: the INV-004 write gate over the symbol map.

An add is accepted only when (a) a verified resolution record for the
symbol exists in the symbol map, and (b) the caller carries an explicit
user-confirmation flag. The 100-active-symbol cap (GOV-004) is
enforced here. Additions enqueue the 5-year backfill gap (executed by
sync in TP-009).

Implements: REQ-SI-FR-004, REQ-SI-INV-004, REQ-SI-GOV-004 (ADR-003)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from stockinsider.data.store.resolver import backfill_window

ACTIVE_CAP = 100


class WatchlistError(RuntimeError):
    """Explicit watchlist refusal (gate, cap, or unknown symbol).

    Implements: REQ-SI-INV-004 (ADR-003)
    """


class WatchlistService:
    """Add / remove / list with the INV-004 gate and GOV-004 cap.

    Implements: REQ-SI-FR-004, REQ-SI-INV-004, REQ-SI-GOV-004 (ADR-003)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self) -> list[dict[str, Any]]:
        """Active watchlist rows joined with symbol names.

        Implements: REQ-SI-FR-004 (ADR-003)
        """
        rows = self._conn.execute(
            """
            SELECT w.canonical_symbol, w.added_at, w.added_via,
                   s.official_name, s.exchange, s.asset_type
            FROM watchlist w JOIN symbols s USING (canonical_symbol)
            WHERE w.status = 'active'
            ORDER BY w.canonical_symbol
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def add_verified(self, canonical_symbol: str, *, user_confirmed: bool, via: str) -> dict[str, Any]:
        """Add a symbol — only through the INV-004 gate.

        Refusals (all explicit): no symbol-map record; record not
        verified; user confirmation absent; built-in benchmark indices;
        cap reached. Every refusal leaves the watchlist unchanged.

        Implements: REQ-SI-FR-004, REQ-SI-INV-004, REQ-SI-GOV-004 (ADR-003)
        """
        if not user_confirmed:
            raise WatchlistError(
                f"refused: {canonical_symbol!r} lacks explicit user confirmation "
                "(INV-004); present the resolved candidate and confirm first"
            )
        row = self._conn.execute(
            """
            SELECT official_name, asset_type, verified FROM symbols
            WHERE canonical_symbol = ?
            """,
            (canonical_symbol,),
        ).fetchone()
        if row is None:
            raise WatchlistError(
                f"refused: {canonical_symbol!r} has no verified resolution record "
                "(INV-004); resolve via symbol search first"
            )
        if not row["verified"]:
            raise WatchlistError(f"refused: resolution for {canonical_symbol!r} is not verified (INV-004)")
        if row["asset_type"] == "index":
            raise WatchlistError(
                f"refused: {canonical_symbol!r} is a built-in benchmark index; "
                "benchmarks are always tracked and never watchlist-managed"
            )
        active = self._conn.execute("SELECT COUNT(*) FROM watchlist WHERE status = 'active'").fetchone()[0]
        current = self._conn.execute(
            "SELECT status FROM watchlist WHERE canonical_symbol = ?", (canonical_symbol,)
        ).fetchone()
        if current is None and active >= ACTIVE_CAP:
            raise WatchlistError(
                f"refused: watchlist cap of {ACTIVE_CAP} active symbols reached (GOV-004); remove a symbol first"
            )
        added_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        from_date, to_date = backfill_window()
        detected_at = added_at
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO watchlist (canonical_symbol, added_at, added_via, status)
                VALUES (?, ?, ?, 'active')
                ON CONFLICT(canonical_symbol) DO UPDATE SET
                    status = 'active', added_at = excluded.added_at, added_via = excluded.added_via
                """,
                (canonical_symbol, added_at, via),
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO sync_gaps (canonical_symbol, from_date, to_date, detected_at)
                VALUES (?, ?, ?, ?)
                """,
                (canonical_symbol, from_date, to_date, detected_at),
            )
        return {
            "canonical_symbol": canonical_symbol,
            "official_name": row["official_name"],
            "status": "active",
            "backfill_enqueued": f"{from_date}..{to_date}",
        }

    def remove(self, canonical_symbol: str) -> dict[str, Any]:
        """Deactivate a symbol (history retained; re-add reactivates).

        Implements: REQ-SI-FR-004 (ADR-003)
        """
        row = self._conn.execute(
            "SELECT status FROM watchlist WHERE canonical_symbol = ?", (canonical_symbol,)
        ).fetchone()
        if row is None:
            raise WatchlistError(f"refused: {canonical_symbol!r} is not on the watchlist")
        if row["status"] != "active":
            raise WatchlistError(f"refused: {canonical_symbol!r} is already removed")
        with self._conn:
            self._conn.execute(
                "UPDATE watchlist SET status = 'removed' WHERE canonical_symbol = ?",
                (canonical_symbol,),
            )
        return {"canonical_symbol": canonical_symbol, "status": "removed"}

    def active_count(self) -> int:
        """Number of active symbols (cap enforcement support).

        Implements: REQ-SI-GOV-004 (ADR-003)
        """
        return int(self._conn.execute("SELECT COUNT(*) FROM watchlist WHERE status = 'active'").fetchone()[0])
