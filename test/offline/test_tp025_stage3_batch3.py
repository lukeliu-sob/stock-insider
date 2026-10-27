"""TP-025 stage 3 batch 3: news.recent, news.search and sync.status declare their result fields.

Strictly behavior-neutral, as batches 1 and 2. The budget fields of sync.status stay on the
heuristic (the key-only lookup cannot see their `budget` parent), and the tools with no typed
numeric leaf declare nothing by design. This file pins the declaring set after stage 3.

Implements: REQ-SI-INV-001, REQ-SI-SEC-002 (ADR-005 Am4, ADR-008 phase 3; TP-025)
"""

from __future__ import annotations

import pytest
from test_ingest_eodnews import _run, _seed_watchlist, _Stub, _vendor_item
from test_registry_news_tools import _make

from stockinsider.agent import guardrail_claims
from stockinsider.agent.guardrail_claims import check, index_evidence
from stockinsider.agent.registry import (
    Registry,
    register_data_tools,
    register_market_tools,
    register_news_tools,
    register_sync_tools,
)
from stockinsider.data.store import DataStore
from stockinsider.data.store.db import open_db
from stockinsider.shared.tools import ToolCall

DECLARING = {
    "market.quote", "fundamentals.summary", "market.indicators", "news.recent", "news.search", "sync.status",
}
VENDOR_ITEMS = [
    _vendor_item("Tencent Cloud PalmAI Unveils Palm X", link="https://www.example.com/a"),
    _vendor_item("Tencent Holdings buys back shares", link="https://www.example.com/b",
                 date="2026-09-26T08:00:00+00:00"),
]


@pytest.fixture()
def registry(tmp_path):
    conn = open_db(tmp_path / "batch3.sqlite")
    _seed_watchlist(conn)
    _run(conn, _Stub({"0700.HK": VENDOR_ITEMS}))
    reg = Registry()
    store = DataStore(conn)
    register_data_tools(reg, store)
    register_sync_tools(reg, store)
    register_market_tools(reg, store)
    register_news_tools(reg, store)
    yield reg
    conn.close()


def run(registry: Registry, tool: str, arguments: dict, seq: int = 1) -> dict:
    result = registry.execute(ToolCall(tool=tool, arguments=arguments, call_id=f"c{seq}"))
    assert result.ok, result.error
    return {f"turn-0001/{tool}#{seq}": result.result}


def specs_of(registry: Registry) -> dict:
    return {spec.name: spec for spec in registry.list_tools()}


def typed(snapshot: dict, specs: dict | None = None) -> list[tuple[float, str]]:
    return [(entry.value, entry.field) for entry in index_evidence(snapshot, specs).entries]


@pytest.fixture()
def search(tmp_path):
    conn, registry, _ = _make(tmp_path, [1.0, 0.0, 0.0, 0.0])
    yield registry
    conn.close()


def test_news_typing_equals_heuristic(registry, search) -> None:
    for reg, snapshot in (
        (registry, run(registry, "news.recent", {"symbol": "0700.HK"})),
        (search, run(search, "news.search", {"query": "Fed rate decision", "k": 3})),
    ):
        assert typed(snapshot)
        assert index_evidence(snapshot, specs_of(reg)).entries == index_evidence(snapshot).entries


def test_sync_status_typing_equals_heuristic(registry) -> None:
    snapshot = run(registry, "sync.status", {})
    fields = {field for _, field in typed(snapshot, specs_of(registry))}
    assert {"symbol_count", "api_calls_used", "api_calls_remaining", "api_calls_cap"} <= fields
    assert index_evidence(snapshot, specs_of(registry)).entries == index_evidence(snapshot).entries


def test_news_verdicts_unchanged_with_specs(registry) -> None:
    snapshot = run(registry, "news.recent", {"symbol": "0700.HK"})
    verdicts = []
    for answer in (
        "There are 2 stored articles about Tencent.",
        "The latest article has a sentiment polarity of 0.998 and a positive share of 0.118.",
        "There are 7 stored articles about Tencent.",
        "The latest article has a sentiment polarity of 0.5.",
    ):
        with_specs = check(answer, snapshot, specs_of(registry))
        assert with_specs == check(answer, snapshot)
        verdicts.append(with_specs.passed)
    assert verdicts == [True, True, False, False]


def test_batch3_keys_are_typed_by_declaration(registry, search, monkeypatch) -> None:
    recent = run(registry, "news.recent", {"symbol": "0700.HK"})
    status = run(registry, "sync.status", {}, seq=2)
    found = run(search, "news.search", {"query": "Fed rate decision", "k": 3})
    specs = specs_of(registry) | specs_of(search)
    monkeypatch.setattr(guardrail_claims, "_evidence_field", lambda *args: "fallback")
    recent_fields = {field for _, field in typed(recent, specs)}
    assert recent_fields == {"news_count", "sentiment", "sentiment_negative", "sentiment_neutral", "sentiment_positive"}
    assert {field for _, field in typed(found, specs)} == {"other"}
    status_by_value = typed(status, specs)
    assert ("symbol_count" in {field for _, field in status_by_value})
    # the budget fields are not declared, so they reach the (disabled) heuristic
    budget = status["turn-0001/sync.status#2"]["budget"]
    assert (float(budget["cap"]), "fallback") in status_by_value


def test_sentiment_declarations_match_eodhd_payload(registry) -> None:
    item = run(registry, "news.recent", {"symbol": "0700.HK"})["turn-0001/news.recent#1"]["items"][0]
    assert item["source"] == "eodhd"
    sentiment_keys = {key for key, field in specs_of(registry)["news.recent"].result_fields.items()
                      if field.field.startswith("sentiment")}
    assert sentiment_keys == set(item["sentiment"]) == set(_vendor_item()["sentiment"])


def test_budget_keys_are_not_declared_anywhere(registry, search) -> None:
    for spec in (specs_of(registry) | specs_of(search)).values():
        assert not {"used", "remaining", "cap"} & set(spec.result_fields), spec.name


def test_declared_count_still_rejects_a_wrong_article_count(registry) -> None:
    snapshot = run(registry, "news.recent", {"symbol": "0700.HK"})
    verdict = check("Tencent has 5 stored news articles.", snapshot, specs_of(registry))
    assert not verdict.passed
    assert "5" in verdict.failed


def test_declaring_tools_after_stage3(registry, search) -> None:
    specs = specs_of(registry) | specs_of(search)
    assert len(specs) == 11
    declaring = {name for name, spec in specs.items() if spec.result_fields or spec.result_discriminators}
    assert declaring == DECLARING
