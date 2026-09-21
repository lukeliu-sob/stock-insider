"""Offline tests for the deterministic info snapshot (TP-010, FR-005).

Implements: REQ-SI-FR-005, REQ-SI-INV-003 (ADR-002)
"""

import json
import re

import pytest
from typer.testing import CliRunner

from stockinsider.cli.app import app
from stockinsider.data import open_data_store
from stockinsider.data.ingest.fundamentals import EodhdFundamentalsAdapter
from stockinsider.data.ingest.market import parse_eod_rows, store_bars
from stockinsider.data.store.info import SymbolUnknown, render_info
from stockinsider.data.store.resolver import Resolution, record_resolution

runner = CliRunner()

DATES = [f"2026-08-{d:02d}" for d in range(3, 31) if d % 2 == 1]  # odd days: 14 sessions


def _bars_body(dates: list[str]) -> str:
    return json.dumps(
        [
            {
                "date": d,
                "open": 100 + i,
                "high": 101 + i,
                "low": 99 + i,
                "close": 100 + i,
                "adjusted_close": 99.5 + i,
                "volume": 1_000_000 + i,
            }
            for i, d in enumerate(dates)
        ]
    )


FUND_BODY = json.dumps(
    {
        "General": {"Name": "TENCENT HOLDINGS LTD", "Exchange": "HK", "Sector": "Comm Services"},
        "Income_Statement": {"quarterly": {"2026-06-30": {"totalRevenue": 161e9, "netIncome": 44e9}}},
        "Balance_Sheet": {"quarterly": {"2026-06-30": {"totalAssets": 1.5e12, "totalStockholdersEquity": 730e9}}},
        "Cash_Flow_": {"quarterly": {"2026-06-30": {"totalCashFromOperatingActivities": 56e9}}},
    }
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKINSIDER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    ds = open_data_store()
    record_resolution(ds.conn, Resolution(canonical_symbol="0700.HK", exchange="HK", official_name="Tencent"))
    store_bars(ds.conn, "0700.HK", parse_eod_rows(_bars_body(DATES), "0700.HK"))
    EodhdFundamentalsAdapter(transport=lambda url, params: FetchResultStub(FUND_BODY)).fetch_and_store(
        ds.conn, "0700.HK"
    )
    yield ds
    ds.close()


class FetchResultStub:
    status = 200

    def __new__(cls, body):  # minimal FetchResult-like
        from stockinsider.data.ingest.http import FetchResult

        return FetchResult(200, body)


def test_info_renders_from_db_only(store) -> None:
    lines = render_info(store.conn, "0700.HK")
    joined = "\n".join(lines)
    assert "TENCENT HOLDINGS LTD" in joined
    assert "quote (2026-08-29" in joined
    assert "fundamentals (quarter ending 2026-06-30)" in joined
    assert "revenue 161.00B" in joined
    # providers unreachable by construction: no provider is ever imported here
    result = runner.invoke(app, ["info", "0700.HK"])
    assert result.exit_code == 0
    assert "quote (2026-08-29" in result.output


def test_info_missing_data_explicit(store) -> None:
    with pytest.raises(SymbolUnknown, match="no stored market data"):
        render_info(store.conn, "9999.HK")
    result = runner.invoke(app, ["info", "9999.HK"])
    assert result.exit_code == 1
    assert "no stored market data" in result.output


def test_info_without_fundamentals_renders_unavailable(store) -> None:
    with store.conn:
        store.conn.execute("DELETE FROM fundamentals WHERE canonical_symbol = '0700.HK'")
    lines = render_info(store.conn, "0700.HK")
    joined = "\n".join(lines)
    assert "fundamentals: unavailable" in joined and "not in the current plan" in joined
    assert "quote (2026-08-29" in joined  # quote still renders


def test_every_numeric_carries_date(store) -> None:
    lines = render_info(store.conn, "0700.HK")
    body_lines = lines[1:]  # the header carries the symbol, not displayed values
    numeric_lines = [ln for ln in body_lines if re.search(r"\d", ln)]
    dated = [ln for ln in numeric_lines if re.search(r"\d{4}-\d{2}-\d{2}", ln)]
    assert numeric_lines and len(dated) == len(numeric_lines), lines
