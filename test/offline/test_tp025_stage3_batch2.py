"""TP-025 stage 3 batch 2: market.indicators declares its metric rows through the `metric` discriminator.

Strictly behavior-neutral, as batch 1: each declared class is the one the heuristic's
metric map gives the same row, so the equivalence tests are the main regression check.
The drift test ties the declarations to the metric names the compute module emits.

Implements: REQ-SI-INV-001, REQ-SI-SEC-002 (ADR-005 Am4, ADR-008 phase 3; TP-025)
"""

from __future__ import annotations

import json

import pytest

from stockinsider.agent import guardrail_claims
from stockinsider.agent.guardrail_claims import check, index_evidence
from stockinsider.agent.registry import Registry, register_market_tools
from stockinsider.data.compute import indicators
from stockinsider.data.store import DataStore
from stockinsider.data.store.db import open_db
from stockinsider.shared.tools import ToolCall

KEY = "turn-0001/market.indicators#1"
QUARTERS = [
    ("2025-06-30", 100.0, 20.0),
    ("2025-09-30", 110.0, 22.0),
    ("2025-12-31", 105.0, 21.0),
    ("2026-03-31", 120.0, 24.0),
    ("2026-06-30", 132.0, 27.0),
]
BARS = [{"date": f"2026-08-{i + 1:02d}", "close": 300.0 + (i % 7) - 3 * (i // 10)} for i in range(30)]


@pytest.fixture()
def registry(tmp_path):
    conn = open_db(tmp_path / "batch2.sqlite")
    with conn:
        conn.execute(
            "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified,"
            " source, resolved_at) VALUES ('0700.HK', 'HKEX', 'Tencent Holdings', 'stock', '[]', 1, 'eodhd',"
            " '2026-09-01T00:00:00+00:00')"
        )
        for bar in BARS:
            conn.execute(
                "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close, volume, currency,"
                " source, fetched_at) VALUES ('0700.HK', ?, ?, ?, ?, ?, 0, 'HKD', 'eodhd', '2026-09-01')",
                (bar["date"], bar["close"], bar["close"], bar["close"], bar["close"]),
            )
        for period, revenue, net in QUARTERS:
            conn.execute(
                "INSERT INTO fundamentals (canonical_symbol, period_end, statement_type, data, source,"
                " fetched_at) VALUES ('0700.HK', ?, 'income', ?, 'eodhd', '2026-09-01')",
                (period, json.dumps({"totalRevenue": revenue, "netIncome": net})),
            )
        conn.execute(
            "INSERT INTO fundamentals (canonical_symbol, period_end, statement_type, data, source, fetched_at)"
            " VALUES ('0700.HK', '2026-06-30', 'balance', ?, 'eodhd', '2026-09-01')",
            (json.dumps({"totalAssets": 500.0, "totalStockholdersEquity": 135.0}),),
        )
    reg = Registry()
    register_market_tools(reg, DataStore(conn))
    yield reg
    conn.close()


def snapshot_of(registry: Registry) -> dict:
    result = registry.execute(ToolCall(tool="market.indicators", arguments={"symbol": "0700.HK"}, call_id="c1"))
    assert result.ok, result.error
    return {KEY: result.result}


def specs_of(registry: Registry) -> dict:
    return {spec.name: spec for spec in registry.list_tools()}


def typed(snapshot: dict, specs: dict | None = None) -> list[tuple[float, str]]:
    return [(entry.value, entry.field) for entry in index_evidence(snapshot, specs).entries]


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def test_declared_typing_equals_heuristic_for_indicators(registry) -> None:
    snapshot = snapshot_of(registry)
    fields = {field for _, field in typed(snapshot, specs_of(registry))}
    assert {"roe", "net_margin", "revenue_growth", "volatility", "drawdown", "sessions"} <= fields
    assert index_evidence(snapshot, specs_of(registry)).entries == index_evidence(snapshot).entries


def test_indicator_verdicts_unchanged_with_specs(registry) -> None:
    snapshot = snapshot_of(registry)
    payload = snapshot[KEY]
    roe = payload["profitability"]["roe"]["value"]
    margin = payload["profitability"]["net_margin"]["value"]
    growth = payload["growth"]["revenue_yoy"]["value"]
    volatility = payload["risk"]["volatility"]["value"]
    drawdown = payload["risk"]["max_drawdown"]["value"]
    for answer in (
        f"Tencent's ROE was {percent(roe)} and its net margin {percent(margin)}.",
        f"Revenue grew {percent(growth)} year over year.",
        f"Annualized volatility was {volatility:.4f} and the maximum drawdown {percent(drawdown)}.",
        "Tencent's ROE was 55.0%.",
        "Revenue grew 3% year over year.",
        f"The maximum drawdown was {percent(volatility)}.",
    ):
        assert check(answer, snapshot, specs_of(registry)) == check(answer, snapshot)


def test_indicator_rows_are_typed_by_declaration(registry, monkeypatch) -> None:
    snapshot = snapshot_of(registry)
    payload = snapshot[KEY]
    monkeypatch.setattr(guardrail_claims, "_evidence_field", lambda *args: "fallback")
    by_value = dict(typed(snapshot, specs_of(registry)))
    assert by_value[payload["profitability"]["roe"]["value"]] == "roe"
    assert by_value[payload["profitability"]["net_margin"]["value"]] == "net_margin"
    assert by_value[payload["growth"]["revenue_yoy"]["value"]] == "revenue_growth"
    assert by_value[payload["risk"]["volatility"]["value"]] == "volatility"
    assert by_value[payload["risk"]["max_drawdown"]["value"]] == "drawdown"
    assert by_value[float(payload["risk"]["volatility"]["window"]["sessions"])] == "sessions"
    assert "fallback" not in by_value.values()


def test_discriminator_covers_every_compute_metric(registry) -> None:
    emitted = {
        row["metric"]
        for row in (
            indicators.pe_ratio(300.0, 27.0, 10.0),
            indicators.pb_ratio(300.0, 135.0, 10.0),
            indicators.ps_ratio(300.0, 132.0, 10.0),
            indicators.roe(27.0, 135.0),
            indicators.net_margin(27.0, 132.0),
            indicators.gross_margin(60.0, 132.0),
            indicators.yoy_growth([(period, revenue) for period, revenue, _ in QUARTERS]),
            indicators.annualized_volatility(BARS),
            indicators.max_drawdown(BARS),
        )
        if "value" in row
    }
    assert len(emitted) == 9
    assert set(specs_of(registry)["market.indicators"].result_discriminators["metric"]) == emitted


def test_unknown_metric_row_keeps_heuristic(registry) -> None:
    snapshot = {KEY: {"risk": {"atr": {"metric": "atr_14", "value": 3.2, "unit": "ratio"}}}}
    assert typed(snapshot, specs_of(registry)) == typed(snapshot) == [(3.2, "unknown")]


def test_declared_volatility_still_rejects_a_drawdown_claim(registry) -> None:
    snapshot = snapshot_of(registry)
    volatility = snapshot[KEY]["risk"]["volatility"]["value"]
    assert abs(volatility - snapshot[KEY]["risk"]["max_drawdown"]["value"]) > 0.01
    claimed = percent(volatility)
    verdict = check(f"Tencent's maximum drawdown was {claimed}.", snapshot, specs_of(registry))
    assert not verdict.passed
    assert any(claimed.rstrip("%") in item for item in verdict.failed)


def test_only_batch1_and_batch2_tools_declare(registry) -> None:
    declaring = {
        name for name, spec in specs_of(registry).items() if spec.result_fields or spec.result_discriminators
    }
    assert declaring == {"market.quote", "fundamentals.summary", "market.indicators"}
