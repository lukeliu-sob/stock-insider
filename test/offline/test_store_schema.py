"""Offline tests for the store schema and migration machinery (TP-008).

Covers: fresh migration applies the full v1 table set; reopen is
idempotent; a newer schema version is refused with an explicit error
(INV-003); WAL mode is enabled.

Implements: REQ-SI-FR-003, REQ-SI-FR-004, REQ-SI-INV-003 (ADR-003)
"""

import sqlite3

import pytest

from stockinsider.data.store.db import SchemaVersionError, open_db

V1_TABLES = {
    "symbols",
    "watchlist",
    "market_bars",
    "fundamentals",
    "news",
    "news_quarantine",
    "event_scores",
    "fx_rates",
    "sync_state",
    "sync_gaps",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def test_migration_v1_applies_idempotently(tmp_path) -> None:
    root = tmp_path / "data"
    conn = open_db(root)
    tables = _table_names(conn)
    assert V1_TABLES <= tables
    version = conn.execute("SELECT MAX(version) FROM schema_history").fetchone()[0]
    assert version == 1
    conn.close()
    conn = open_db(root)  # reopen: no re-run, no error
    assert _table_names(conn) == tables
    conn.close()


def test_newer_schema_refused(tmp_path) -> None:
    root = tmp_path / "data"
    conn = open_db(root)
    with conn:
        conn.execute("INSERT INTO schema_history (version, applied_at) VALUES (999, '2049-01-01T00:00:00+00:00')")
    conn.close()
    with pytest.raises(SchemaVersionError, match="newer than this code"):
        open_db(root)


def test_wal_mode_enabled(tmp_path) -> None:
    conn = open_db(tmp_path / "data")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode.lower() == "wal"
