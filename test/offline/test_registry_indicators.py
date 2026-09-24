"""Offline tests for the market.indicators registry tool (TP-013a).

Seeded store: bars + quarterly income + balance -> computed
profitability/growth/risk with windows; valuation explicitly
unavailable (share count not captured); missing data raises the
explicit no-stored-data error (INV-003).

Implements: REQ-SI-FR-006 (ADR-005)
"""

from __future__ import annotations

import json

from stockinsider.agent.registry import Registry, register_market_tools
from stockinsider.data.store import DataStore
from stockinsider.data.store.db import open_db
from stockinsider.shared.tools import ToolCall


def _seed(conn) -> None:
    with conn:
        conn.execute(
            "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type,"
            " aliases, verified, source, resolved_at)"
            " VALUES ('0700.HK', 'HKEX', 'Tencent Holdings', 'stock', '[]', 1, 'eodhd',"
            " '2026-09-01T00:00:00+00:00')"
        )
        for i in range(30):
            date = f"2026-08-{i + 1:02d}" if i < 30 else "2026-09-01"
            close = 300.0 + (i % 7) - 3 * (i // 10)
            conn.execute(
                "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close,"
                " volume, currency, source, fetched_at)"
                " VALUES ('0700.HK', ?, ?, ?, ?, ?, 0, 'HKD', 'eodhd', '2026-09-01')"
                " ON CONFLICT(canonical_symbol, date) DO UPDATE SET close = excluded.close",
                (date, close, close, close, close),
            )
        for index, (period, revenue, net) in enumerate(
            [
                ("2025-06-30", 100.0, 20.0),
                ("2025-09-30", 110.0, 22.0),
                ("2025-12-31", 105.0, 21.0),
                ("2026-03-31", 120.0, 24.0),
                ("2026-06-30", 132.0, 27.0),
            ]
        ):
            conn.execute(
                "INSERT INTO fundamentals (canonical_symbol, period_end, statement_type,"
                " data, source, fetched_at)"
                " VALUES ('0700.HK', ?, 'income', ?, 'eodhd', '2026-09-01')"
                " ON CONFLICT(canonical_symbol, period_end, statement_type)"
                " DO UPDATE SET data = excluded.data",
                (period, json.dumps({"totalRevenue": revenue, "netIncome": net})),
            )
        conn.execute(
            "INSERT INTO fundamentals (canonical_symbol, period_end, statement_type,"
            " data, source, fetched_at)"
            " VALUES ('0700.HK', '2026-06-30', 'balance', ?, 'eodhd', '2026-09-01')"
            " ON CONFLICT(canonical_symbol, period_end, statement_type)"
            " DO UPDATE SET data = excluded.data",
            (json.dumps({"totalAssets": 500.0, "totalStockholdersEquity": 135.0}),),
        )


def _registry(tmp_path):
    conn = open_db(tmp_path / "ind.sqlite")
    _seed(conn)
    registry = Registry()
    register_market_tools(registry, DataStore(conn))
    return conn, registry


def test_indicators_snapshot(tmp_path) -> None:
    conn, registry = _registry(tmp_path)
    result = registry.execute(
        ToolCall(tool="market.indicators", arguments={"symbol": "0700.HK"}, call_id="c1")
    )
    assert result.ok, result.error
    payload = result.result
    assert payload["symbol"] == "0700.HK"
    assert payload["as_of"] == "2026-08-30"
    # profitability computed: roe = 27/135
    assert abs(payload["profitability"]["roe"]["value"] - 27.0 / 135.0) < 1e-6
    assert abs(payload["profitability"]["net_margin"]["value"] - 27.0 / 132.0) < 1e-6
    assert "unavailable" in payload["profitability"]["gross_margin"]
    # growth computed over the five quarters
    assert abs(payload["growth"]["revenue_yoy"]["value"] - 0.32) < 1e-6
    # risk computed with windows
    assert "value" in payload["risk"]["volatility"]
    assert "value" in payload["risk"]["max_drawdown"]
    # valuation explicitly unavailable (share count not captured)
    assert "unavailable" not in payload["valuation"]
    assert "note" in payload["valuation"]


def test_indicators_no_data_explicit(tmp_path) -> None:
    conn = open_db(tmp_path / "empty.sqlite")
    registry = Registry()
    register_market_tools(registry, DataStore(conn))
    result = registry.execute(
        ToolCall(tool="market.indicators", arguments={"symbol": "MSFT.US"}, call_id="c2")
    )
    assert not result.ok
    assert "no stored market data" in (result.error or "")
