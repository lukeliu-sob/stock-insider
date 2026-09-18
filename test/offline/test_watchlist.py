"""Offline tests for the watchlist service and INV-004/GOV-004 gates (TP-008).

Mocked resolver transport: no network. Covers: add requires a verified
resolution record AND explicit confirmation; unresolvable mentions are
reported, watchlist unchanged; the 100-active cap boundary; add/remove
/list round trip; benchmark indices are tracked but never addable.

Implements: REQ-SI-FR-004, REQ-SI-INV-004, REQ-SI-GOV-004 (ADR-003)
"""

import json

import pytest

from stockinsider.data import (
    ACTIVE_CAP,
    WatchlistError,
    open_data_store,
)
from stockinsider.data.store.resolver import Resolution, SymbolResolver

TENCENT_BODY = json.dumps(
    [
        {"Code": "0700", "Exchange": "HK", "Name": "TENCENT HOLDINGS LTD", "Type": "Common Stock"},
        {"Code": "0700", "Exchange": "US", "Name": "0700 METRIC LP", "Type": "Common Stock"},
    ]
)


def _store(tmp_path, body: str | None = TENCENT_BODY) -> "object":
    ds = open_data_store(tmp_path / "data")
    if body is not None:
        ds.resolver = SymbolResolver(transport=lambda url, params: body, api_key="test-key")
    return ds


def test_seed_benchmarks_present(tmp_path) -> None:
    ds = _store(tmp_path)
    row = ds._conn.execute(  # noqa: SLF001 — test seam
        "SELECT official_name, asset_type FROM symbols WHERE canonical_symbol = 'HSI.IND'"
    ).fetchone()
    assert row is not None and row["asset_type"] == "index"
    ds.close()


def test_add_requires_verified_resolution(tmp_path) -> None:
    ds = _store(tmp_path)
    with pytest.raises(WatchlistError, match="no verified resolution record"):
        ds.watchlist.add_verified("9999.HK", user_confirmed=True, via="cli")
    assert ds.watchlist.active_count() == 0
    ds.close()


def test_add_without_confirmation_refused(tmp_path) -> None:
    ds = _store(tmp_path)
    candidates = ds.resolver.search("Tencent Holdings")
    ds.record(candidates[0])
    with pytest.raises(WatchlistError, match="explicit user confirmation"):
        ds.watchlist.add_verified("0700.HK", user_confirmed=False, via="cli")
    assert ds.watchlist.active_count() == 0
    ds.close()


def test_add_with_confirmation_happy_path(tmp_path) -> None:
    ds = _store(tmp_path)
    candidates = ds.resolver.search("Tencent Holdings")
    assert candidates[0].canonical_symbol == "0700.HK"
    ds.record(candidates[0])
    result = ds.watchlist.add_verified("0700.HK", user_confirmed=True, via="cli")
    assert result["status"] == "active"
    assert ".." in result["backfill_enqueued"]  # 5y window queued (TP-009 executes)
    gap = ds._conn.execute(  # noqa: SLF001 — test seam
        "SELECT * FROM sync_gaps WHERE canonical_symbol = '0700.HK'"
    ).fetchone()
    assert gap is not None
    ds.close()


def test_unresolvable_mention_reported(tmp_path) -> None:
    ds = _store(tmp_path, body="[]")
    assert ds.resolver.search("zzz-no-such-company") == []
    assert ds.watchlist.active_count() == 0
    ds.close()


def test_cap_100(tmp_path) -> None:
    ds = _store(tmp_path)
    for i in range(ACTIVE_CAP):
        symbol = f"S{i:03d}.US"
        ds.record(Resolution(canonical_symbol=symbol, exchange="US", official_name=f"Stock {i}"))
        ds.watchlist.add_verified(symbol, user_confirmed=True, via="cli")
    assert ds.watchlist.active_count() == ACTIVE_CAP
    ds.record(Resolution(canonical_symbol="OVER.US", exchange="US", official_name="Over Cap"))
    with pytest.raises(WatchlistError, match="cap of 100"):
        ds.watchlist.add_verified("OVER.US", user_confirmed=True, via="cli")
    assert ds.watchlist.active_count() == ACTIVE_CAP
    ds.close()


def test_remove_list_roundtrip(tmp_path) -> None:
    ds = _store(tmp_path)
    cand = ds.resolver.search("Tencent Holdings")[0]
    ds.record(cand)
    ds.watchlist.add_verified("0700.HK", user_confirmed=True, via="cli")
    rows = ds.watchlist.list()
    assert [row["canonical_symbol"] for row in rows] == ["0700.HK"]
    result = ds.watchlist.remove("0700.HK")
    assert result["status"] == "removed"
    assert ds.watchlist.active_count() == 0
    with pytest.raises(WatchlistError, match="already removed"):
        ds.watchlist.remove("0700.HK")
    ds.close()


def test_benchmark_index_add_refused(tmp_path) -> None:
    ds = _store(tmp_path)
    with pytest.raises(WatchlistError, match="built-in benchmark index"):
        ds.watchlist.add_verified("HSI.IND", user_confirmed=True, via="cli")
    assert ds.watchlist.active_count() == 0
    ds.close()
