"""TP-015 PR-b: direct-symbol verification + candidate governance.

Implements: REQ-SI-FR-004, REQ-SI-INV-004 (ADR-002, BD-017)
"""

from __future__ import annotations

import json
import pytest

from stockinsider.data.ingest.http import FetchResult
from stockinsider.data.ingest.market import EodhdMarketAdapter
from stockinsider.data.store import open_data_store
from stockinsider.data.store.resolver import (
    Resolution,
    SYMBOL_SHAPE,
    fold_secondaries,
    order_candidates,
    parse_search_response,
)


def _resolution(symbol: str, exchange: str, kind: str = "stock") -> Resolution:
    return Resolution(canonical_symbol=symbol, exchange=exchange, official_name=f"name {symbol}", asset_type=kind)


def _adapter(body: str) -> EodhdMarketAdapter:
    return EodhdMarketAdapter(transport=lambda url, params: FetchResult(200, body), api_key="test-key")


EOD_BODY = json.dumps(
    [
        {
            "date": "2026-09-25",
            "open": 540.0,
            "high": 545.0,
            "low": 539.0,
            "close": 544.0,
            "adjusted_close": 544.0,
            "volume": 12000000,
        }
    ]
)


# -- shape gate ---------------------------------------------------------------


def test_symbol_shape_gate() -> None:
    assert SYMBOL_SHAPE.match("0700.HK") and SYMBOL_SHAPE.match("9988.HK")
    assert SYMBOL_SHAPE.match("AAPL.US") and SYMBOL_SHAPE.match("T.US")
    assert not SYMBOL_SHAPE.match("Tencent Holdings")
    assert not SYMBOL_SHAPE.match("0700 HK")
    assert not SYMBOL_SHAPE.match("AAPL.MU")  # secondary venue: vendor search covers it


# -- ordering and folding (pure) ----------------------------------------------


def test_order_candidates_ranks_exact_primary_then_adr() -> None:
    rows = [
        _resolution("AAPL.MU", "MU"),
        _resolution("AAPL.US", "US", "adr"),
        _resolution("AAPL.US", "US"),
        _resolution("MSFT.US", "US"),
    ]
    out = order_candidates(rows, "aapl.us")
    assert out[0].canonical_symbol == "AAPL.US" and out[0].asset_type == "stock"
    assert out[1].asset_type == "adr"
    assert out[2].canonical_symbol == "MSFT.US"
    assert out[3].exchange == "MU"


def test_order_candidates_stable_within_group() -> None:
    rows = [_resolution(f"S{i}.US", "US") for i in range(5)]
    assert [c.canonical_symbol for c in order_candidates(rows, "q")] == [f"S{i}.US" for i in range(5)]


def test_fold_secondaries_collapses_non_primary_venues() -> None:
    rows = (
        [_resolution("AAPL.US", "US")]
        + [_resolution(f"AAPL.{code}", code) for code in ("XETRA", "LSE", "BA", "BK", "MU")]
        + [_resolution("AAPL.HK", "HK")]
    )
    visible, count, exchanges = fold_secondaries(rows)
    assert [c.exchange for c in visible] == ["US", "HK"]
    assert count == 5
    assert set(exchanges) == {"XETRA", "LSE", "BA", "BK", "MU"}


def test_parse_search_response_asset_classes() -> None:
    body = json.dumps(
        [
            {"Code": "0700", "Exchange": "HK", "Name": "TENCENT", "Type": "Common Stock"},
            {"Code": "BABA", "Exchange": "US", "Name": "Alibaba ADR", "Type": "ADR"},
            {"Code": "SPY", "Exchange": "US", "Name": "SPDR ETF", "Type": "ETF"},
            {"Code": "XYZ", "Exchange": "US", "Name": "XYZ FUND", "Type": "Fund"},
            {"Code": "QQQ", "Exchange": "US", "Name": "no type row", "Type": None},
        ]
    )
    kinds = [c.asset_type for c in parse_search_response(body)]
    assert kinds == ["stock", "adr", "etf", "fund", "other"]


# -- direct verification (BD-017) ---------------------------------------------


def test_verify_symbol_returns_unverified_name_and_spends_budget(tmp_path) -> None:
    ds = open_data_store(tmp_path / "d1")
    resolution = ds.verify_symbol("0700.HK", adapter=_adapter(EOD_BODY))
    assert resolution is not None
    assert resolution.canonical_symbol == "0700.HK"
    assert resolution.exchange == "HK"
    assert "name unverified" in resolution.official_name
    assert resolution.asset_type == "unverified"
    from stockinsider.data.ingest.budget import CallBudget

    assert CallBudget(ds._conn).used_today() == 1  # noqa: SLF001 — test seam
    ds.close()


def test_verify_symbol_no_data_returns_none_still_spends(tmp_path) -> None:
    ds = open_data_store(tmp_path / "d2")
    assert ds.verify_symbol("9999.HK", adapter=_adapter("[]")) is None
    from stockinsider.data.ingest.budget import CallBudget

    assert CallBudget(ds._conn).used_today() == 1  # noqa: SLF001 — test seam
    ds.close()


def test_verify_symbol_dead_adapter_refused(tmp_path, monkeypatch) -> None:
    # Hermetic (TP-018): a developer machine with a real EODHD key in the
    # local environment made this "dead adapter" case silently live —
    # offline tests must never depend on ambient secrets.
    monkeypatch.setattr("stockinsider.data.ingest.market.env_value", lambda _name: None)
    ds = open_data_store(tmp_path / "d3")
    with pytest.raises(Exception, match="not configured"):
        ds.verify_symbol("0700.HK", adapter=EodhdMarketAdapter())
    ds.close()


def test_direct_verification_never_bypasses_inv4(tmp_path) -> None:
    """Verified existence does NOT bypass user confirmation (INV-004)."""
    from stockinsider.data.store.watchlist import WatchlistError

    ds = open_data_store(tmp_path / "d4")
    resolution = ds.verify_symbol("0700.HK", adapter=_adapter(EOD_BODY))
    assert resolution is not None
    ds.record(resolution)
    with pytest.raises(WatchlistError, match="explicit user confirmation"):
        ds.watchlist.add_verified("0700.HK", user_confirmed=False, via="cli")
    assert ds.watchlist.active_count() == 0
    ds.close()


def test_direct_verification_then_confirm_adds(tmp_path) -> None:
    ds = open_data_store(tmp_path / "d5")
    resolution = ds.verify_symbol("0700.HK", adapter=_adapter(EOD_BODY))
    assert resolution is not None
    ds.record(resolution)
    result = ds.watchlist.add_verified("0700.HK", user_confirmed=True, via="cli")
    assert result["status"] == "active"
    ds.close()
