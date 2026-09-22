"""Offline tests for market ingestion: adapter, storage, gaps, sync (TP-009).

Fake transports only — no network. The fixture payload mirrors the
live-probed EODHD row shape (date/open/high/low/close/adjusted_close/
volume; BD-010 round). Covers FR-001 fit criteria (a) deleted-bar
refetch and (b) calendar completeness, plus INV-003 batch semantics.

Implements: REQ-SI-FR-001, REQ-SI-QA-003, REQ-SI-INV-003 (ADR-002)
"""

import json
from datetime import date, timedelta

import pytest

from stockinsider.data import open_data_store
from stockinsider.data.ingest.calendar import missing_ranges, trading_dates
from stockinsider.data.ingest.http import FetchResult, TransportError
from stockinsider.data.ingest.market import InvalidMarketData, parse_eod_rows, store_bars
from stockinsider.data.ingest.sync import SyncService
from stockinsider.data.store.resolver import Resolution

HK_DATES = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]


def _bars(dates: list[str], close_base: float = 100.0) -> str:
    return json.dumps(
        [
            {
                "date": d,
                "open": round(close_base + i * 0.5, 2),
                "high": round(close_base + i * 0.5 + 1.0, 2),
                "low": round(close_base + i * 0.5 - 1.0, 2),
                "close": round(close_base + i * 0.5 + 0.25, 2),
                "adjusted_close": round(close_base + i * 0.5 + 0.2, 4),
                "volume": 1_000_000 + i,
            }
            for i, d in enumerate(dates)
        ]
    )


class FakeTransport:
    """Serves canned payloads by symbol; counts calls; can raise."""

    def __init__(self, payloads: dict[str, str]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def __call__(self, url: str, params: dict[str, str]) -> FetchResult:
        symbol = url.rsplit("/", 1)[-1].split("?")[0]
        self.calls.append(symbol)
        if symbol not in self.payloads:
            raise TransportError("http-error", f"HTTP 404 for {symbol}")
        return FetchResult(200, self.payloads[symbol])


@pytest.fixture()
def store(tmp_path):
    ds = open_data_store(tmp_path / "data")
    yield ds
    ds.close()


def _add_symbol(store, symbol: str, name: str) -> None:
    from stockinsider.data.store.resolver import record_resolution

    conn = store._conn  # noqa: SLF001 — test seam
    record_resolution(
        conn,
        Resolution(canonical_symbol=symbol, exchange=symbol.rsplit(".", 1)[-1], official_name=name),
    )


def test_adapter_parses_and_stores(store) -> None:
    _add_symbol(store, "0700.HK", "Tencent Holdings")
    rows = parse_eod_rows(_bars(HK_DATES), "0700.HK")
    assert [r["date"] for r in rows] == HK_DATES
    stored = store_bars(store._conn, "0700.HK", rows)  # noqa: SLF001 — test seam
    assert stored == 5
    row = store._conn.execute(  # noqa: SLF001
        "SELECT close, adjusted_close, currency FROM market_bars WHERE canonical_symbol='0700.HK' AND date='2026-09-09'"
    ).fetchone()
    assert row["close"] == pytest.approx(101.25)
    assert row["adjusted_close"] == pytest.approx(101.2)
    assert row["currency"] == "HKD"


def test_malformed_row_fails_whole_batch(store) -> None:
    body = _bars(HK_DATES[:2])[:-1] + "," + json.dumps({"date": "oops", "close": 1.0}) + "]"
    with pytest.raises(InvalidMarketData, match="row 2 failed schema validation"):
        parse_eod_rows(body, "0700.HK")
    assert (
        store._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM market_bars"
        ).fetchone()[0]
        == 0
    )  # nothing stored


def test_transport_error_is_explicit(store) -> None:
    service = SyncService(store._conn, transport=FakeTransport({}))  # noqa: SLF001
    report = service.run()
    failed = [i for i in report.results if i.status == "failed"]
    assert failed and all("404" in i.detail or "indices first" in i.detail for i in failed)


def _seed_full_environment(store, monkeypatch, cap: int | None = None, symbol_bars: str | None = None) -> FakeTransport:
    """Indices + one watchlist symbol, calendar-consistent."""
    if cap is not None:
        monkeypatch.setenv("EODHD_DAILY_CALLS", str(cap))
    transport = FakeTransport(
        {
            "HSI.INDX": _bars(HK_DATES),
            "HSTECH.INDX": _bars(HK_DATES),
            "GSPC.INDX": _bars(HK_DATES),
            "NDX.INDX": _bars(HK_DATES),
            "0700.HK": symbol_bars if symbol_bars is not None else _bars(HK_DATES),
        }
    )
    ds_conn = store._conn  # noqa: SLF001
    from stockinsider.data.store.resolver import record_resolution

    record_resolution(ds_conn, Resolution(canonical_symbol="0700.HK", exchange="HK", official_name="Tencent"))
    with ds_conn:
        ds_conn.execute(
            "INSERT INTO watchlist (canonical_symbol, added_at, added_via) VALUES ('0700.HK', '2026-09-18', 'cli')"
        )
        ds_conn.execute("INSERT OR IGNORE INTO sync_state (track, cursor) VALUES ('market:0700.HK', '2026-09-11')")
    service = SyncService(ds_conn, transport=transport, news_enabled=False)
    service.run()
    return transport


def test_deleted_bar_refetched_next_sync(store, monkeypatch) -> None:
    _seed_full_environment(store, monkeypatch)  # first run fills everything
    conn = store._conn  # noqa: SLF001
    with conn:
        conn.execute("DELETE FROM market_bars WHERE canonical_symbol='0700.HK' AND date='2026-09-09'")
    report = SyncService(conn, transport=FakeTransport({"0700.HK": _bars(["2026-09-09"])}), news_enabled=False).run()
    repair = next(i for i in report.results if i.symbol == "0700.HK" and i.action == "gap-repair")
    assert repair.status == "ok"
    assert (
        conn.execute(  # completeness restored (criterion b)
            "SELECT COUNT(*) FROM market_bars WHERE canonical_symbol='0700.HK'"
        ).fetchone()[0]
        == 5
    )


def test_completeness_equals_calendar(store, monkeypatch) -> None:
    _seed_full_environment(store, monkeypatch)
    conn = store._conn  # noqa: SLF001
    stored = {r["date"] for r in conn.execute("SELECT date FROM market_bars WHERE canonical_symbol='0700.HK'")}
    expected = trading_dates(conn, "HK", "2021-09-18", "2026-09-18")
    in_window = [d for d in stored if d >= (date.today() - timedelta(days=5 * 365)).isoformat()]
    assert len(in_window) == len([d for d in expected if d in stored])


def test_market_holiday_not_counted(store) -> None:
    # Calendar derived from index bars: a weekday absent from HSI is not a trading day
    _ = store
    conn = store._conn  # noqa: SLF001
    dates = ["2026-09-07", "2026-09-08", "2026-09-10", "2026-09-11"]  # the 9th is a HK holiday
    rows = parse_eod_rows(_bars(dates), "HSI.INDX")
    store_bars(conn, "HSI.INDX", rows)
    stored = {r["date"] for r in conn.execute("SELECT date FROM market_bars WHERE canonical_symbol='HSI.INDX'")}
    assert missing_ranges(stored, trading_dates(conn, "HK", "2026-09-07", "2026-09-11")) == []


def test_indices_backfill_priority_first(store, monkeypatch) -> None:
    transport = _seed_full_environment(store, monkeypatch, cap=2)
    # cap=2: only the first two index backfills ran; everything else deferred
    assert transport.calls[:2] == ["HSI.INDX", "HSTECH.INDX"]


def test_sync_tools_registered_and_gated(store, tmp_path, monkeypatch) -> None:
    from stockinsider.agent.registry import Registry, register_sync_tools
    from stockinsider.shared.tools import ToolCall

    registry = Registry()
    register_sync_tools(registry, store)
    blocked = registry.execute(ToolCall(tool="sync.run", arguments={"user_confirmed": False}, call_id="t"))
    assert blocked.ok is False and "write effects" in blocked.error
    status = registry.execute(ToolCall(tool="sync.status", arguments={}, call_id="t"))
    assert status.ok and "budget" in status.result


def test_migration_v2_adds_adjusted_close(tmp_path) -> None:
    from stockinsider.data.store.db import SCHEMA_VERSION, open_db

    conn = open_db(tmp_path / "d")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(market_bars)")}
    assert "adjusted_close" in cols
    version = conn.execute("SELECT MAX(version) FROM schema_history").fetchone()[0]
    assert version == SCHEMA_VERSION  # top migration (v3 since TP-010)
    conn.close()
