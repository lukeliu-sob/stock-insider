"""TP-025 stage 3 batch 1: market.quote and fundamentals.summary declare their result fields.

The batch is strictly behavior-neutral (owner decision 2026-10-27): every declaration
reproduces the class the heuristic gives the same leaf, so the equivalence tests are the
main regression check. The drift tests tie the declarations to the facade's real keys.

Implements: REQ-SI-INV-001, REQ-SI-SEC-002 (ADR-005 Am4, ADR-008 phase 3; TP-025)
"""

from __future__ import annotations

import json

import pytest

from stockinsider.agent import guardrail_claims
from stockinsider.agent.guardrail_claims import check, index_evidence
from stockinsider.agent.registry import Registry, register_market_tools
from stockinsider.data.store import DataStore
from stockinsider.data.store.db import open_db
from stockinsider.shared.tools import ToolCall

VENDOR_INCOME = {"totalRevenue": 161.0e9, "netIncome": 44.0e9, "grossProfit": 90.0e9, "costOfRevenue": 71.0e9}
VENDOR_BALANCE = {"totalAssets": 1.5e12, "totalStockholdersEquity": 730.0e9}
BATCH1 = ("market.quote", "fundamentals.summary")


@pytest.fixture()
def registry(tmp_path):
    conn = open_db(tmp_path / "batch1.sqlite")
    with conn:
        conn.execute(
            "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified,"
            " source, resolved_at) VALUES ('0700.HK', 'HKEX', 'Tencent Holdings', 'stock', '[]', 1, 'eodhd',"
            " '2026-10-24T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close, adjusted_close,"
            " volume, currency, source, fetched_at)"
            " VALUES ('0700.HK', '2026-10-23', 640.5, 648.0, 636.0, 644.63, 641.2, 18250000, 'HKD',"
            " 'eodhd', '2026-10-24')"
        )
        for statement_type, data in (("income", VENDOR_INCOME), ("balance", VENDOR_BALANCE)):
            conn.execute(
                "INSERT INTO fundamentals (canonical_symbol, period_end, statement_type, data, source,"
                " fetched_at) VALUES ('0700.HK', '2026-06-30', ?, ?, 'eodhd', '2026-10-24')",
                (statement_type, json.dumps(data)),
            )
    reg = Registry()
    register_market_tools(reg, DataStore(conn))
    yield reg
    conn.close()


def snapshot_of(registry: Registry) -> dict:
    snapshot = {}
    for seq, tool in enumerate(BATCH1, start=1):
        result = registry.execute(ToolCall(tool=tool, arguments={"symbol": "0700.HK"}, call_id=f"c{seq}"))
        assert result.ok, result.error
        snapshot[f"turn-0001/{tool}#{seq}"] = result.result
    return snapshot


def specs_of(registry: Registry) -> dict:
    return {spec.name: spec for spec in registry.list_tools()}


def typed(snapshot: dict, specs: dict | None = None) -> list[tuple[float, str]]:
    return [(entry.value, entry.field) for entry in index_evidence(snapshot, specs).entries]


def test_declared_typing_equals_heuristic_for_batch1(registry) -> None:
    snapshot = snapshot_of(registry)
    by_value = dict(typed(snapshot, specs_of(registry)))
    assert by_value[644.63] == "close"
    assert by_value[18250000.0] == "volume"
    assert by_value[161.0e9] == "revenue"
    assert by_value[730.0e9] == "equity"
    assert typed(snapshot, specs_of(registry)) == typed(snapshot)


def test_index_evidence_unchanged_with_batch1_specs(registry) -> None:
    snapshot = snapshot_of(registry)
    assert index_evidence(snapshot, specs_of(registry)).entries == index_evidence(snapshot).entries
    for answer in (
        "Tencent closed at 644.63 HKD on 2026-10-23, on volume of 18,250,000 shares.",
        "Tencent closed at 650 HKD.",
        "Revenue for the quarter was 161 billion and net income 44 billion.",
        "Gross profit was 95 billion.",
    ):
        assert check(answer, snapshot, specs_of(registry)) == check(answer, snapshot)


def test_batch1_keys_are_typed_by_declaration(registry, monkeypatch) -> None:
    snapshot = snapshot_of(registry)
    monkeypatch.setattr(guardrail_claims, "_evidence_field", lambda *args: "fallback")
    by_value = dict(typed(snapshot, specs_of(registry)))
    for value, declared in (
        (640.5, "open"), (648.0, "high"), (636.0, "low"), (644.63, "close"), (641.2, "adjusted_close"),
        (18250000.0, "volume"), (161.0e9, "revenue"), (44.0e9, "net_income"), (90.0e9, "gross_profit"),
        (730.0e9, "equity"),
    ):
        assert by_value[value] == declared
    # undeclared vendor keys and coverage ratios still go through the fallback
    assert by_value[71.0e9] == "fallback"
    assert by_value[1.5e12] == "fallback"


def test_quote_declarations_match_facade_columns(registry) -> None:
    quote = snapshot_of(registry)["turn-0001/market.quote#1"]
    numeric = {key for key, value in quote.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
    assert set(specs_of(registry)["market.quote"].result_fields) == numeric


def test_fundamentals_declarations_are_vendor_case(registry) -> None:
    declared = specs_of(registry)["fundamentals.summary"].result_fields
    vendor_keys = set(VENDOR_INCOME) | set(VENDOR_BALANCE)
    statement_keys = {key for key in declared if key not in {"quarters", "quarters_expected", "cells"}}
    assert statement_keys <= vendor_keys
    evidence = index_evidence({}, specs_of(registry))
    assert guardrail_claims._declared_field(evidence, "fundamentals.summary", "totalRevenue", {}) == "revenue"
    assert guardrail_claims._declared_field(evidence, "fundamentals.summary", "totalrevenue", {}) is None


def test_declared_close_still_rejects_a_volume_claim(registry) -> None:
    snapshot = snapshot_of(registry)
    answer = "Tencent traded a volume of 644.63 shares."
    verdict = check(answer, snapshot, specs_of(registry))
    assert not verdict.passed
    assert "644.63" in verdict.failed


def test_undeclared_tools_keep_heuristic(registry) -> None:
    # migrated by the TP-025 batch-2 amendment: market.indicators now declares (owner-approved)
    specs = specs_of(registry)
    declaring = {*BATCH1, "market.indicators"}
    assert all(
        not spec.result_fields and not spec.result_discriminators
        for name, spec in specs.items()
        if name not in declaring
    )
