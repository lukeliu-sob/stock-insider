"""Free-tier call budget: check-and-spend against the daily cap.

The counter lives in sync_state (track 'eodhd-budget') and resets
lazily: a stale date row reads as zero. Default cap 20 (free tier);
EODHD_DAILY_CALLS overrides (tests, or a paid tier — capacity is
bought, per ADR-002). Exhaustion is reported explicitly by the sync
service, never silently absorbed (INV-003).

Implements: REQ-SI-INV-003 (ADR-002)
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from stockinsider.shared.envfile import env_value

BUDGET_TRACK = "eodhd-budget"
DEFAULT_DAILY_CALLS = 20
CAP_ENV = "EODHD_DAILY_CALLS"


def daily_cap() -> int:
    """The day's call cap: EODHD_DAILY_CALLS (env or env-file) or the free-tier default.

    Implements: REQ-SI-INV-003 (ADR-002)
    """
    raw = os.environ.get(CAP_ENV) or env_value(CAP_ENV)
    if raw and raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_DAILY_CALLS


class CallBudget:
    """Check-and-spend accounting persisted in sync_state.

    Implements: REQ-SI-INV-003 (ADR-002)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def used_today(self) -> int:
        """Calls spent today (a stale-date row reads as zero — lazy reset).

        Implements: REQ-SI-INV-003 (ADR-002)
        """
        row = self._conn.execute(
            "SELECT calls_today, calls_date FROM sync_state WHERE track = ?", (BUDGET_TRACK,)
        ).fetchone()
        if row is None or row["calls_date"] != self._today():
            return 0
        return int(row["calls_today"])

    def remaining(self) -> int:
        """Calls left today.

        Implements: REQ-SI-INV-003 (ADR-002)
        """
        return max(0, daily_cap() - self.used_today())

    def spend(self, n: int = 1) -> None:
        """Record n spent calls (no check — callers use try_spend).

        Implements: REQ-SI-INV-003 (ADR-002)
        """
        today = self._today()
        used = self.used_today()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO sync_state (track, cursor, last_run_at, last_status, calls_today, calls_date)
                VALUES (?, NULL, ?, 'spend', ?, ?)
                ON CONFLICT(track) DO UPDATE SET
                    calls_today = excluded.calls_today, calls_date = excluded.calls_date,
                    last_run_at = excluded.last_run_at, last_status = excluded.last_status
                """,
                (BUDGET_TRACK, datetime.now(timezone.utc).isoformat(timespec="seconds"), used + n, today),
            )

    def try_spend(self, n: int = 1) -> bool:
        """Atomically check-and-spend; False means 'deferred' (explicit upstream).

        Implements: REQ-SI-INV-003 (ADR-002)
        """
        if self.remaining() < n:
            return False
        self.spend(n)
        return True
