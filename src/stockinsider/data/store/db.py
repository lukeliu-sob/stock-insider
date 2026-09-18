"""Connection management and migration runner for the SQLite store.

The store lives at <data-root>/stockinsider.db (WAL mode, foreign keys
on). Schema versions are tracked in schema_history; the code refuses
databases from a newer schema with an explicit error (INV-003
semantics — never open what it cannot faithfully read).

Implements: REQ-SI-FR-003, REQ-SI-FR-004 (ADR-003)
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from stockinsider.data.store.schema import MIGRATIONS, SCHEMA_VERSION

DB_FILENAME = "stockinsider.db"


class SchemaVersionError(RuntimeError):
    """Database schema is newer than the code (explicit, fail-closed).

    Implements: REQ-SI-INV-003 (ADR-003)
    """


def data_root(root: Path | str | None = None) -> Path:
    """Resolve the data root: explicit, then env override, then ./data.

    Mirrors the agent-side resolution convention
    (STOCKINSIDER_DATA_ROOT); duplicated locally because data must not
    import agent modules (dependency law, blueprint §5).

    Implements: REQ-SI-FR-011 (ADR-003)
    """
    if root is not None:
        return Path(root)
    return Path(os.environ.get("STOCKINSIDER_DATA_ROOT", "data"))


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_history").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def open_db(root: Path | str | None = None) -> sqlite3.Connection:
    """Open (and migrate, once) the authoritative store.

    Fail-closed rules: newer schemas are refused; every migration runs
    inside one transaction; WAL and foreign keys are enforced per
    connection.

    Implements: REQ-SI-FR-004, REQ-SI-INV-003 (ADR-003)
    """
    path = data_root(root) / DB_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_history (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    current = _current_version(conn)
    if current > SCHEMA_VERSION:
        conn.close()
        raise SchemaVersionError(
            f"database schema version {current} is newer than this code "
            f"(supports {SCHEMA_VERSION}); upgrade the application instead of "
            "opening it blindly (INV-003)"
        )
    for index, ddl in enumerate(MIGRATIONS, start=1):
        if index <= current:
            continue
        applied_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with conn:  # one transaction per migration (memory-design §4)
            conn.executescript(ddl)
            conn.execute(
                "INSERT INTO schema_history (version, applied_at) VALUES (?, ?)",
                (index, applied_at),
            )
    return conn
