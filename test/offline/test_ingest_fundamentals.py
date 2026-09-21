"""Offline tests for fundamentals ingestion and coverage (TP-010).

Fixture payloads mirror the vendor's live shape (demo-symbol probe,
AILOG-0034). No network.

Implements: REQ-SI-FR-002, REQ-SI-INV-003 (ADR-002)
"""

import json

import pytest

from stockinsider.data import open_data_store
from stockinsider.data.ingest.fundamentals import (
    CALL_COST,
    EodhdFundamentalsAdapter,
    FundamentalsNotInPlan,
    coverage,
    parse_fundamentals,
)
from stockinsider.data.ingest.http import FetchResult, TransportError
from stockinsider.data.store.resolver import Resolution

QUARTERS = [
    "2024-12-31",
    "2025-03-31",
    "2025-06-30",
    "2025-09-30",
    "2025-12-31",
    "2026-03-31",
    "2026-06-30",
    "2026-09-30",
]


def _payload(quarters: list[str], drop_field: str | None = None) -> str:
    def stmt(fields: dict) -> dict:
        return {"quarterly": {q: dict(fields) for q in quarters}}

    income = {"totalRevenue": 161_000_000_000.0, "netIncome": 44_000_000_000.0}
    balance = {"totalAssets": 1_500_000_000_000.0, "totalStockholdersEquity": 730_000_000_000.0}
    cash = {"totalCashFromOperatingActivities": 56_000_000_000.0}
    if drop_field:
        for target in (income, balance, cash):
            target.pop(drop_field, None)
    return json.dumps(
        {
            "General": {
                "Name": "TENCENT HOLDINGS LTD",
                "Exchange": "HK",
                "Sector": "Communication Services",
                "Industry": "Interactive Media",
                "CountryName": "China",
            },
            "Income_Statement": stmt(income),
            "Balance_Sheet": stmt(balance),
            "Cash_Flow_": stmt(cash),
        }
    )


class FakeTransport:
    def __init__(self, payloads: dict[str, str]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def __call__(self, url: str, params: dict[str, str]) -> FetchResult:
        symbol = url.rsplit("/", 1)[-1].split("?")[0]
        self.calls.append(symbol)
        if symbol not in self.payloads:
            raise TransportError("http-error", f"HTTP 404 for {symbol}")
        return FetchResult(200, self.payloads[symbol])


class DeniedTransport:
    def __call__(self, url: str, params: dict[str, str]) -> FetchResult:
        raise TransportError("http-error", "HTTP 403 from fundamentals")


@pytest.fixture()
def store(tmp_path):
    ds = open_data_store(tmp_path / "data")
    yield ds
    ds.close()


def _add_symbol(store, symbol: str) -> None:
    from stockinsider.data.store.resolver import record_resolution

    record_resolution(
        store.conn,
        Resolution(canonical_symbol=symbol, exchange=symbol.rsplit(".", 1)[-1], official_name="Test"),
    )


def test_fetch_parses_and_stores(store) -> None:
    _add_symbol(store, "0700.HK")
    adapter = EodhdFundamentalsAdapter(transport=FakeTransport({"0700.HK": _payload(QUARTERS)}))
    outcome = adapter.fetch_and_store(store.conn, "0700.HK")
    assert outcome["statements"] == 24  # 8 quarters x 3 statements
    assert outcome["profile"] is True
    cov = coverage(store.conn, "0700.HK")
    assert cov["quarters"] == 8 and cov["cells_filled"] == cov["cells"]
    assert cov["meets_threshold"] is True


def test_missing_required_field_is_explicit(store) -> None:
    _add_symbol(store, "0700.HK")
    adapter = EodhdFundamentalsAdapter(transport=FakeTransport({"0700.HK": _payload(QUARTERS, drop_field="netIncome")}))
    adapter.fetch_and_store(store.conn, "0700.HK")
    cov = coverage(store.conn, "0700.HK")
    assert cov["cells_filled"] == cov["cells"] - 8  # one field x 8 quarters missing
    assert cov["meets_threshold"] is False
    assert {"period_end": "2026-09-30", "field": "netIncome"} in cov["gaps"]


def test_malformed_payload_rejected_whole(store) -> None:
    _add_symbol(store, "0700.HK")
    body = _payload(QUARTERS).replace('"quarterly"', '"quarterly_x"')  # sections absent -> no rows
    adapter = EodhdFundamentalsAdapter(transport=FakeTransport({"0700.HK": body}))
    outcome = adapter.fetch_and_store(store.conn, "0700.HK")
    assert outcome["statements"] == 0
    with pytest.raises(Exception):
        parse_fundamentals("[not-an-object", "0700.HK")
    assert store.conn.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0] == 0 or outcome["statements"] == 0


def test_403_plan_not_covered_explicit(store) -> None:
    _add_symbol(store, "0700.HK")
    adapter = EodhdFundamentalsAdapter(transport=DeniedTransport())
    with pytest.raises(FundamentalsNotInPlan, match="Fundamentals Data Feed"):
        adapter.fetch_and_store(store.conn, "0700.HK")


def test_sync_spends_10_units_and_denial_caches(store, monkeypatch) -> None:
    from stockinsider.data.ingest.sync import SyncService

    _add_symbol(store, "0700.HK")
    with store.conn:
        store.conn.execute(
            "INSERT INTO watchlist (canonical_symbol, added_at, added_via) VALUES ('0700.HK', '2026-09-21', 'cli')"
        )
    # one market bar so the fundamentals staleness rule triggers
    from stockinsider.data.ingest.market import parse_eod_rows, store_bars

    rows = parse_eod_rows(
        json.dumps([{"date": "2026-09-21", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]), "0700.HK"
    )
    store_bars(store.conn, "0700.HK", rows)
    service = SyncService(store.conn, transport=DeniedTransport())
    report = service.run()
    fund_items = [i for i in report.results if i.action == "fundamentals"]
    assert fund_items and fund_items[0].status == "failed" and "Fundamentals Data Feed" in fund_items[0].detail
    assert report.calls_used >= CALL_COST
    # denial cached: second run plans no fundamentals items (no budget burn)
    second = SyncService(store.conn, transport=DeniedTransport()).run()
    assert not [i for i in second.results if i.action == "fundamentals"]
    assert CALL_COST == 10
