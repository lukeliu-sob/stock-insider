"""TP-040: defects the 2026-11-03 CLI smoke test found on a real store.

Migration v9 restores HKEX-spelled primary rows that v6 demoted; a
direct-verification placeholder is never a verified name; tool calls
record a session's subject symbols; a keyless sync fails before it
spends budget; the CLI shows the exchange and last-active date and
normalizes lowercase symbols.

Implements: REQ-SI-FR-001, REQ-SI-FR-004, REQ-SI-FR-005, REQ-SI-FR-012, REQ-SI-INV-001, REQ-SI-INV-003, REQ-SI-INV-004 (ADR-002, ADR-003, ADR-005 Am4)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stockinsider.agent.session import SessionStore
from stockinsider.cli.app import _canonical, app
from stockinsider.data import open_data_store
from stockinsider.data.ingest.budget import CallBudget
from stockinsider.data.ingest.http import FetchResult, TransportError
from stockinsider.data.ingest.market import store_bars
from stockinsider.data.ingest.sync import SyncService
from stockinsider.data.store.schema import MIGRATIONS
from test_tp022_slash_writes import FakeDataStore, _plain

runner = CliRunner()

PLACEHOLDER = "1211.HK (name unverified - vendor search does not index this exchange; verify before adding)"
NOT_CONFIGURED = "market ingestion is not configured"


def _symbol(conn, symbol: str, exchange: str, name: str, verified: int) -> None:
    conn.execute(
        "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified, source,"
        " resolved_at) VALUES (?, ?, ?, 'stock', '[]', ?, 'test', '2026-09-27T03:44:06+00:00')",
        (symbol, exchange, name, verified),
    )


def _bars(n: int = 3) -> list[dict]:
    return [
        {
            "date": f"2026-09-{10 + i:02d}",
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "adjusted_close": 100.5 + i,
            "volume": 1_000_000 + i,
        }
        for i in range(n)
    ]


@pytest.fixture()
def no_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    env_file = tmp_path / "empty.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(env_file))
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    monkeypatch.setenv("STOCKINSIDER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("STOCKINSIDER_SESSIONS_ROOT", str(tmp_path / "sessions"))
    return tmp_path


# ---- 1. migration v9 ---------------------------------------------------------


def _migrated(rows: list[tuple[str, str, str]]) -> dict[str, tuple[str, int]]:
    """Run v1, seed rows as verified, run v2..v9; return exchange and flag."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(MIGRATIONS[0])
    for symbol, exchange, name in rows:
        _symbol(conn, symbol, exchange, name, 1)
    for migration in MIGRATIONS[1:]:
        conn.executescript(migration)
    out = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT canonical_symbol, exchange, verified FROM symbols")}
    conn.close()
    return out


def test_v9_restores_hkex_spelled_primary_rows() -> None:
    rows = _migrated([("0700.HK", "HKEX", "Tencent Holdings Ltd"), ("9988.HK", "SEHK", "Alibaba Group Holding Ltd")])
    assert rows == {"0700.HK": ("HK", 1), "9988.HK": ("HK", 1)}


def test_v9_leaves_secondary_and_placeholder_rows() -> None:
    rows = _migrated(
        [
            ("SAP.DE", "XETRA", "SAP SE"),
            ("1211.HK", "HKEX", PLACEHOLDER),
            ("AAPL.US", "NASDAQ", "Apple Inc"),
        ]
    )
    assert rows == {"SAP.DE": ("XETRA", 0), "1211.HK": ("HKEX", 0), "AAPL.US": ("NASDAQ", 0)}


# ---- 2. placeholder names ----------------------------------------------------


def test_verified_names_drops_placeholder(tmp_path: Path) -> None:
    store = open_data_store(str(tmp_path / "data"))
    with store._conn:  # noqa: SLF001
        _symbol(store._conn, "0700.HK", "HK", "Tencent Holdings Ltd", 1)  # noqa: SLF001
        _symbol(store._conn, "1211.HK", "HK", PLACEHOLDER, 1)  # noqa: SLF001
    try:
        assert store.verified_names(["0700.HK", "1211.HK"]) == {"0700.HK": "Tencent Holdings Ltd"}
    finally:
        store.close()


# ---- 3. session subject symbols ----------------------------------------------


def _call(store: SessionStore, session_id: str, tool: str, arguments: dict) -> None:
    store.append_event(session_id, {"event": "tool-call", "tool": tool, "arguments": arguments, "turn": "turn-0001"})


def test_tool_call_symbol_becomes_session_subject(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    sid = store.create()["session_id"]
    _call(store, sid, "market.quote", {"symbol": "0700.HK"})
    _call(store, sid, "news.recent", {"symbol": "1211.HK", "k": 8})
    _call(store, sid, "market.indicators", {"symbol": "0700.HK"})
    assert [row["session_id"] for row in store.list_sessions(symbol="0700.HK")] == [sid]
    assert store.list_sessions()[0]["subject_symbols"] == ["0700.HK", "1211.HK"]


def test_session_lookup_and_non_symbols_are_not_subjects(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    sid = store.create()["session_id"]
    _call(store, sid, "session.list", {"symbol": "0700.HK"})
    _call(store, sid, "symbol.search", {"query": "BYD"})
    _call(store, sid, "market.quote", {"symbol": "tencent"})
    _call(store, sid, "market.quote", {"symbol": "0700.HK; DROP"})
    assert store.list_sessions()[0]["subject_symbols"] == []
    assert store.list_sessions(symbol="0700.HK") == []


def test_subject_update_keeps_event_log_append_only(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    sid = store.create()["session_id"]
    log = tmp_path / "sessions" / sid / "session.jsonl"
    before = log.read_bytes()
    _call(store, sid, "market.quote", {"symbol": "0700.HK"})
    after = log.read_bytes()
    assert after.startswith(before)
    assert json.loads(after[len(before) :])["arguments"] == {"symbol": "0700.HK"}


def test_cli_sessions_shows_last_active(no_key: Path) -> None:
    store = SessionStore()
    sid = store.create()["session_id"]
    _call(store, sid, "market.quote", {"symbol": "0700.HK"})
    last = store.list_sessions()[0]["last_active"]
    result = runner.invoke(app, ["sessions", "--symbol", "0700.HK"])
    assert result.exit_code == 0
    assert sid in result.output and f"last {last}" in result.output


# ---- 4. keyless sync ---------------------------------------------------------


def test_keyless_sync_spends_no_budget(no_key: Path) -> None:
    store = open_data_store()
    try:
        report = SyncService(store._conn, news_enabled=False).run()  # noqa: SLF001
        market = [item for item in report.results if item.action != "fundamentals"]
        assert market and all(item.status == "failed" and NOT_CONFIGURED in item.detail for item in market)
        assert report.calls_used == 0
        assert CallBudget(store._conn).used_today() == 0  # noqa: SLF001
    finally:
        store.close()


def test_keyed_sync_still_spends(no_key: Path) -> None:
    calls: list[str] = []

    def transport(url: str, params: dict) -> FetchResult:
        calls.append(url)
        raise TransportError("http-error", "HTTP 404")

    store = open_data_store()
    try:
        report = SyncService(store._conn, transport=transport, news_enabled=False).run()  # noqa: SLF001
        assert calls, "an injected transport is live"
        assert report.calls_used == len(calls)
    finally:
        store.close()


# ---- 5. CLI details ----------------------------------------------------------


def _seed_quote(symbol: str, exchange: str) -> None:
    store = open_data_store()
    try:
        with store._conn:  # noqa: SLF001
            _symbol(store._conn, symbol, exchange, "Tencent Holdings Ltd", 1)  # noqa: SLF001
        store_bars(store._conn, symbol, _bars())  # noqa: SLF001
    finally:
        store.close()


def test_info_header_names_exchange(no_key: Path) -> None:
    _seed_quote("0700.HK", "HK")
    _seed_quote("9988.HK", "")  # bars need a map row (foreign key); its exchange can be blank
    named = runner.invoke(app, ["info", "0700.HK"])
    unnamed = runner.invoke(app, ["info", "9988.HK"])
    assert named.exit_code == 0 and "exchange HK" in named.output.splitlines()[0]
    assert unnamed.exit_code == 0 and "exchange unknown" in unnamed.output.splitlines()[0]


def test_lowercase_symbol_is_normalized(no_key: Path) -> None:
    _seed_quote("0700.HK", "HK")
    result = runner.invoke(app, ["info", "0700.hk"])
    assert result.exit_code == 0
    assert result.output.startswith("0700.HK")
    assert _canonical(" hsi.indx ") == "HSI.INDX"
    assert _canonical("Tencent") == "Tencent"
    assert _canonical("Tencent Holdings.") == "Tencent Holdings."


def test_repl_symbol_arguments_are_normalized(no_key: Path) -> None:
    data = FakeDataStore()
    out = _plain(SessionStore(), data, ["/watch remove 0700.hk", "y", "/exit"])
    assert data.watchlist.calls == [("remove", "0700.HK")]
    assert "removed 0700.HK" in out
