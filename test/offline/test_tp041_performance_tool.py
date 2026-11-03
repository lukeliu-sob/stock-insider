"""TP-041: market.performance, trailing-window price changes as a registry tool.

The arithmetic is `data/compute.period_performance`; the registry relays
it. A window the stored history cannot cover is unavailable with its
reason. No-data conditions fail closed as a clean LookupError. Signed
percent claims verify against the tool's result under the unchanged
post-check.

Implements: REQ-SI-FR-006, REQ-SI-FR-008, REQ-SI-INV-001, REQ-SI-INV-003 (ADR-005 Am5)
"""

from __future__ import annotations

import pytest

from stockinsider.agent.guardrail_claims import check
from stockinsider.agent.registry import Registry, register_market_tools, register_performance_tools
from stockinsider.agent.repl import build_registry
from stockinsider.agent.session import SessionStore
from stockinsider.data.compute import pct_change, period_performance
from stockinsider.data.store import DataStore
from stockinsider.data.store.db import open_db
from stockinsider.shared.tools import ToolCall

KEY = "turn-0001/market.performance#1"


def _closes(n: int) -> list[float]:
    return [400.0 + (i % 6) * 3.5 - i * 0.75 for i in range(n)]


def _bars(closes: list[float]) -> list[dict]:
    return [{"date": f"2026-0{8 + i // 28}-{1 + i % 28:02d}", "close": close} for i, close in enumerate(closes)]


@pytest.fixture()
def store(tmp_path):
    conn = open_db(tmp_path / "perf.sqlite")
    with conn:
        conn.execute(
            "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified, source,"
            " resolved_at) VALUES ('0700.HK', 'HK', 'Tencent Holdings Ltd', 'stock', '[]', 1, 'test',"
            " '2026-09-01T00:00:00+00:00')"
        )
        for bar in _bars(_closes(30)):
            conn.execute(
                "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close, adjusted_close, volume,"
                " currency, source, fetched_at) VALUES ('0700.HK', ?, ?, ?, ?, ?, ?, 0, 'HKD', 'test', '2026-09-30')",
                (bar["date"], bar["close"], bar["close"], bar["close"], bar["close"], bar["close"]),
            )
    yield DataStore(conn)
    conn.close()


def _registry(store) -> Registry:
    reg = Registry()
    register_market_tools(reg, store)
    register_performance_tools(reg, store)
    return reg


def _performance(reg: Registry, symbol: str = "0700.HK"):
    return reg.execute(ToolCall(tool="market.performance", arguments={"symbol": symbol}, call_id="c1"))


def test_period_performance_rows() -> None:
    closes = _closes(30)
    out = period_performance(_bars(closes))
    by_window = {row["sessions"]: row for row in out["windows"]}
    assert sorted(by_window) == [5, 20]
    for sessions in (5, 20):
        row = by_window[sessions]
        assert row["from_adjusted_close"] == closes[-sessions - 1]
        assert row["adjusted_close"] == closes[-1]
        assert row["change_pct"] == round(pct_change(closes[-sessions - 1], closes[-1]), 4)
        assert row["to_date"] == _bars(closes)[-1]["date"]
    assert [(u["sessions"], u["reason"]) for u in out["unavailable"]] == [
        (60, "only 30 stored sessions; 61 needed"),
        (250, "only 30 stored sessions; 251 needed"),
    ]


def test_period_performance_zero_base_is_unavailable() -> None:
    closes = _closes(30)
    closes[-6] = 0.0
    out = period_performance(_bars(closes), windows=(5, 20))
    assert [row["sessions"] for row in out["windows"]] == [20]
    assert out["unavailable"][0]["sessions"] == 5
    assert "previous value is zero" in out["unavailable"][0]["reason"]


def test_market_performance_tool_result(store) -> None:
    result = _performance(_registry(store))
    assert result.ok, result.error
    payload = result.result
    assert payload["symbol"] == "0700.HK" and payload["as_of"] == _bars(_closes(30))[-1]["date"]
    assert payload["official_name"] == "Tencent Holdings Ltd"
    assert payload["price_basis"] == "adjusted close"
    assert [row["sessions"] for row in payload["windows"]] == [5, 20]
    assert [u["sessions"] for u in payload["unavailable"]] == [60, 250]
    assert result.provenance["source_kind"] == "computed"


def test_market_performance_unknown_symbol_fails_closed(store) -> None:
    result = _performance(_registry(store), "9999.HK")
    assert not result.ok
    assert "LookupError: 9999.HK: no stored market data (sync first; INV-003)" in result.error
    assert "KeyError" not in result.error and "'9999.HK" not in result.error


def test_market_quote_no_data_error_is_clean(store) -> None:
    result = _registry(store).execute(ToolCall(tool="market.quote", arguments={"symbol": "9999.HK"}, call_id="c2"))
    assert not result.ok
    assert "LookupError: 9999.HK: no stored market data" in result.error
    assert "KeyError" not in result.error


def test_signed_performance_claims_verify(store) -> None:
    reg = _registry(store)
    snapshot = {KEY: _performance(reg).result}
    specs = {spec.name: spec for spec in reg.list_tools()}
    month = next(row for row in snapshot[KEY]["windows"] if row["sessions"] == 20)
    claimed = f"{month['change_pct']:.2f}"
    prose = check(f"Over the last 20 sessions 0700.HK moved {claimed}%.", snapshot, specs)
    table = check(f"| Window | Change |\n|---|---|\n| 20 sessions | {claimed}% |", snapshot, specs)
    assert prose.passed, prose.failed
    assert table.passed, table.failed
    wrong = check("Over the last 20 sessions 0700.HK moved -3.5%.", snapshot, specs)
    assert not wrong.passed and any("3.5" in item for item in wrong.failed)


def test_build_registry_exposes_market_performance(store, tmp_path) -> None:
    sessions = SessionStore(tmp_path / "sessions")
    with_data = {spec.name for spec in build_registry(sessions, data_store=store).list_tools()}
    without = {spec.name for spec in build_registry(sessions).list_tools()}
    assert "market.performance" in with_data
    assert "market.performance" not in without
