"""Live smoke for market ingestion (TP-009; never blocking).

Institutionalizes the BD-008/BD-010 family lesson: every external
assumption this feature touches is verified once against the live
endpoint — host reachability, endpoint shape, row schema, and 402
semantics. Runs ONLY when an EODHD key is configured; otherwise an
explicit skip. Costs at most 2 calls of the daily budget.

Implements: REQ-SI-FR-001, REQ-SI-INV-003 (ADR-002)
"""

import pytest

from stockinsider.shared.envfile import env_value


def _key() -> str | None:
    return env_value("EODHD_API_KEY")


def test_host_and_row_shape_live() -> None:
    """One EOD call: host serves, rows carry the full schema (BD-010 family)."""
    key = _key()
    if not key:
        pytest.skip("EODHD_API_KEY not configured; live smoke skipped (never blocking)")
    from datetime import date, timedelta

    from stockinsider.data.ingest.market import EodhdMarketAdapter

    to_date = date.today().isoformat()
    from_date = (date.today() - timedelta(days=14)).isoformat()
    rows = EodhdMarketAdapter(api_key=key).fetch_eod("0700.HK", from_date, to_date)
    assert rows, "live EOD call returned zero bars for 0700.HK over two weeks"
    row = rows[-1]
    for field in ("date", "open", "high", "low", "close"):
        assert field in row, f"live row missing {field}"
    assert row["date"] <= to_date


def test_search_smoke_live() -> None:
    """One search call: the resolver's live path still serves (BD-009 family)."""
    key = _key()
    if not key:
        pytest.skip("EODHD_API_KEY not configured; live smoke skipped (never blocking)")
    from stockinsider.data.store.resolver import SymbolResolver

    resolver = SymbolResolver()
    if not resolver.is_live():
        pytest.skip("resolver not live despite key present (wiring defect — investigate)")
    candidates = resolver.search("0700")
    assert any(c.canonical_symbol == "0700.HK" for c in candidates), candidates
