"""TP-025 stage 4: subject-bearing results carry the verified `official_name` (DE-16, in-ledger class).

Names reach the guardrail's existing name path (`_collect_names`), so a number attributed by
company name to the wrong in-ledger subject is flagged. Unverified names are an explicit null.
The E-010 tests run the corpora on name-bearing copies of the ledgers and pin the residuals:
H047 (companies absent from the ledger) and the postposed-subject false flags H021/H030.

Implements: REQ-SI-INV-001, REQ-SI-INV-003 (ADR-005 Am4, ADR-008 phase 3; TP-025)
"""

from __future__ import annotations

import copy

import pytest
import test_tp024_typed_claims as e010
from test_registry_news_tools import _make

from stockinsider.agent.guardrail_claims import check, index_evidence
from stockinsider.agent.registry import Registry, register_market_tools, register_news_tools
from stockinsider.data.store import DataStore
from stockinsider.data.store.db import open_db
from stockinsider.shared.tools import ToolCall

PLACEHOLDER = "1211.HK (name unverified - vendor search does not index this exchange; verify before adding)"
NAMED_TOOLS = ("market.quote", "market.indicators", "fundamentals.summary", "news.recent")
E010_NAMES = {"0700.HK": "Tencent Holdings Ltd", "1211.HK": "BYD Company Ltd", "AAPL.US": "Apple Inc"}


def _seed_symbol(conn, symbol: str, name: str, *, verified: int, drift: float) -> None:
    conn.execute(
        "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified, source,"
        " resolved_at) VALUES (?, 'HK', ?, 'stock', '[]', ?, 'eodhd', '2026-10-01T00:00:00+00:00')",
        (symbol, name, verified),
    )
    for i in range(30):
        close = 100.0 + drift * ((i * 7) % 5) - (i // 10)
        conn.execute(
            "INSERT INTO market_bars (canonical_symbol, date, open, high, low, close, volume, currency, source,"
            " fetched_at) VALUES (?, ?, ?, ?, ?, ?, 1000, 'HKD', 'eodhd', '2026-10-01')",
            (symbol, f"2026-09-{i + 1:02d}", close, close, close, close),
        )
    conn.execute(
        "INSERT INTO fundamentals (canonical_symbol, period_end, statement_type, data, source, fetched_at)"
        " VALUES (?, '2026-06-30', 'income', '{\"totalRevenue\": 10.0, \"netIncome\": 2.0}', 'eodhd', '2026-10-01')",
        (symbol,),
    )
    conn.execute(
        "INSERT INTO news (url_norm, url_raw, title, domain, published_at, fetched_at, source_query, symbol,"
        " relevance_score, kept, source) VALUES (?, ?, 'Headline', 'reuters.com', '20260930T090000Z',"
        " '2026-10-01T00:00:00+00:00', 'test', ?, 2.0, 1, 'eodhd')",
        (f"https://example.com/{symbol}", f"https://example.com/{symbol}", symbol),
    )


@pytest.fixture()
def store(tmp_path):
    conn = open_db(tmp_path / "stage4.sqlite")
    with conn:
        _seed_symbol(conn, "0700.HK", "Tencent Holdings Ltd", verified=1, drift=1.0)
        _seed_symbol(conn, "1211.HK", PLACEHOLDER, verified=0, drift=4.0)
    yield DataStore(conn)
    conn.close()


def registry_for(store) -> Registry:
    reg = Registry()
    register_market_tools(reg, store)
    register_news_tools(reg, store)
    return reg


def run(reg: Registry, tool: str, symbol: str) -> dict:
    result = reg.execute(ToolCall(tool=tool, arguments={"symbol": symbol}, call_id="c1"))
    assert result.ok, result.error
    return result.result


def test_tools_return_verified_official_name(store, tmp_path) -> None:
    reg = registry_for(store)
    for tool in NAMED_TOOLS:
        assert run(reg, tool, "0700.HK")["official_name"] == "Tencent Holdings Ltd", tool
    conn, search, _ = _make(tmp_path, [0.0, 0.0, 1.0, 0.0])
    with conn:
        conn.execute(
            "INSERT INTO symbols (canonical_symbol, exchange, official_name, asset_type, aliases, verified, source,"
            " resolved_at) VALUES ('0700.HK', 'HK', 'Tencent Holdings Ltd', 'stock', '[]', 1, 'eodhd',"
            " '2026-10-01T00:00:00+00:00')"
        )
    result = search.execute(ToolCall(tool="news.search", arguments={"query": "Tencent games", "k": 1}, call_id="s1"))
    assert result.ok, result.error
    top = result.result["results"][0]
    assert (top["bucket"], top["official_name"]) == ("0700.HK", "Tencent Holdings Ltd")
    conn.close()


def test_unverified_symbol_gets_null_name(store) -> None:
    reg = registry_for(store)
    for tool in NAMED_TOOLS:
        payload = run(reg, tool, "1211.HK")
        assert "official_name" in payload and payload["official_name"] is None, tool


def test_macro_bucket_row_gets_null_name(tmp_path) -> None:
    conn, search, _ = _make(tmp_path, [1.0, 0.0, 0.0, 0.0])
    result = search.execute(ToolCall(tool="news.search", arguments={"query": "Fed", "k": 1}, call_id="s1"))
    assert result.ok, result.error
    top = result.result["results"][0]
    assert top["bucket"] == "macro:fed" and top["official_name"] is None
    conn.close()


def test_facade_without_lookup_yields_null(store) -> None:
    class StandIn:
        def market_quote(self, symbol):
            return store.market_quote(symbol)

    reg = Registry()
    register_market_tools(reg, StandIn())
    assert run(reg, "market.quote", "0700.HK")["official_name"] is None


def test_name_misattribution_is_flagged(tmp_path) -> None:
    conn = open_db(tmp_path / "pair.sqlite")
    with conn:
        _seed_symbol(conn, "0700.HK", "Tencent Holdings Ltd", verified=1, drift=1.0)
        _seed_symbol(conn, "1211.HK", "BYD Company Ltd", verified=1, drift=4.0)
    reg = registry_for(DataStore(conn))
    ledger = {
        f"turn-0001/market.indicators#{seq}": run(reg, "market.indicators", symbol)
        for seq, symbol in enumerate(("0700.HK", "1211.HK"), start=1)
    }
    tencent, byd = (ledger[f"turn-0001/market.indicators#{seq}"]["risk"]["volatility"]["value"] for seq in (1, 2))
    assert abs(tencent - byd) > 0.05
    assert check(f"Tencent's annualized volatility was {tencent * 100:.1f}%.", ledger).passed
    wrong = check(f"Tencent's annualized volatility was {byd * 100:.1f}%.", ledger)
    assert not wrong.passed
    assert f"{byd * 100:.1f}" in wrong.failed
    conn.close()


def test_bucket_row_feeds_a_name_and_macro_does_not() -> None:
    ledger = {
        "turn-0001/news.search#1": {
            "results": [
                {"news_id": 3, "bucket": "0700.HK", "official_name": "Tencent Holdings Ltd", "distance": 0.1},
                {"news_id": 1, "bucket": "macro:fed", "official_name": "Federal Reserve", "distance": 0.2},
            ]
        }
    }
    assert index_evidence(ledger).names == {"Tencent": "0700.HK"}


def test_placeholder_name_never_becomes_a_subject(store) -> None:
    reg = registry_for(store)
    ledger = {f"turn-0001/{tool}#1": run(reg, tool, "1211.HK") for tool in NAMED_TOOLS}
    assert index_evidence(ledger).names == {}


def _named_ledgers() -> dict:
    ledgers = copy.deepcopy(e010.LEDGERS)
    for ledger in ledgers.values():
        for key, result in ledger.items():
            if any(tool in key for tool in NAMED_TOOLS) and isinstance(result, dict):
                if result.get("symbol") in E010_NAMES:
                    result["official_name"] = E010_NAMES[result["symbol"]]
    return ledgers


def test_e010_dev_with_names(monkeypatch) -> None:
    monkeypatch.setattr(e010, "LEDGERS", _named_ledgers())
    result = e010._evaluate(e010.DEV["items"])
    assert result["escapes"] == [] and result["false_flags"] == [] and result["extra_flags"] == []


#: Residuals on name-bearing ledgers (stage 4, owner decision 2026-10-27): H047 names companies absent
#: from its ledger (DE-16 stays open); H021/H030 put the subject after the number ("for BYD"), which
#: `_resolve_subject` does not prefer - measured in stage 5, not fixed here.
NAMED_ESCAPES = {("H047", "46.49"), ("H047", "6")}
NAMED_FALSE_FLAGS = {("H023", "19"), ("H023", "36"), ("H021", "18,982,584"), ("H030", "15.23")}


def test_e010_heldout_with_names(monkeypatch) -> None:
    monkeypatch.setattr(e010, "LEDGERS", _named_ledgers())
    result = e010._evaluate(e010.HELD_OUT["items"])
    assert set(result["escapes"]) == NAMED_ESCAPES, sorted(set(result["escapes"]) ^ NAMED_ESCAPES)
    flagged = set(result["false_flags"]) | set(result["extra_flags"])
    assert flagged == NAMED_FALSE_FLAGS, sorted(flagged ^ NAMED_FALSE_FLAGS)
    assert 1 - len(result["false_flags"]) / len(result["correct"]) >= 0.90
