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
        "SELECT official_name, asset_type FROM symbols WHERE canonical_symbol = 'HSI.INDX'"
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


def test_list_surfaces_a_demoted_verified_flag(tmp_path) -> None:
    """DE-11 (TP-026 plan): a symbol added while verified, then later
    demoted by a migration like v6 (ADR-005 Am2 secondary-venue scope),
    stays active and keeps syncing - that was already true before this
    fix. What changes: `list()` surfaces the flag instead of staying
    silent about the mismatch."""
    ds = _store(tmp_path)
    cand = ds.resolver.search("Tencent Holdings")[0]
    ds.record(cand)
    ds.watchlist.add_verified("0700.HK", user_confirmed=True, via="cli")
    before = ds.watchlist.list()[0]
    assert before["canonical_symbol"] == "0700.HK"
    assert before["verified"]
    with ds._conn:  # noqa: SLF001 — test seam, simulating a migration demotion
        ds._conn.execute("UPDATE symbols SET verified = 0 WHERE canonical_symbol = '0700.HK'")  # noqa: SLF001
    after = ds.watchlist.list()
    assert [row["canonical_symbol"] for row in after] == ["0700.HK"]  # still active, still listed
    assert not after[0]["verified"]
    ds.close()


def test_benchmark_index_add_refused(tmp_path) -> None:
    ds = _store(tmp_path)
    with pytest.raises(WatchlistError, match="built-in benchmark index"):
        ds.watchlist.add_verified("HSI.INDX", user_confirmed=True, via="cli")
    assert ds.watchlist.active_count() == 0
    ds.close()


def test_reactivation_respects_cap(tmp_path) -> None:
    """M10: re-adding a removed symbol at a full watchlist is refused."""
    from stockinsider.data.store.watchlist import ACTIVE_CAP, WatchlistError

    ds = _store(tmp_path, body=None)
    ds.watchlist._conn.execute("PRAGMA writable_schema = 0")  # noqa: SLF001 — noop guard
    conn = ds._conn  # noqa: SLF001 — test seam
    with conn:
        for i in range(ACTIVE_CAP):
            sym = f"{i:04d}.HK"
            conn.execute(
                "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type,"
                " aliases, verified, source, resolved_at) VALUES (?, 'HK', ?, 'stock',"
                " '[]', 1, 'test', '2026-09-29')",
                (sym, f"sym {i}"),
            )
            conn.execute(
                "INSERT INTO watchlist (canonical_symbol, added_at, added_via, status)"
                " VALUES (?, '2026-09-29T00:00:00+00:00', 'cli', 'active')",
                (sym,),
            )
        # a verified, previously-removed symbol at a full watchlist
        conn.execute(
            "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type,"
            " aliases, verified, source, resolved_at) VALUES ('0700.HK', 'HK', 'Tencent',"
            " 'stock', '[]', 1, 'test', '2026-09-29')"
        )
        conn.execute(
            "INSERT INTO watchlist (canonical_symbol, added_at, added_via, status)"
            " VALUES ('0700.HK', '2026-09-29T00:00:00+00:00', 'cli', 'removed')"
        )
    with pytest.raises(WatchlistError, match="cap"):
        ds.watchlist.add_verified("0700.HK", user_confirmed=True, via="cli")
    ds.close()
