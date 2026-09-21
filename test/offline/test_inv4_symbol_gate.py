"""Adversarial suite for INV-004: nothing enters the watchlist unverified (TP-008).

Zero tolerance: fabricated tickers, missing confirmation flags, and
exchange collisions must yield 0 additions — asserted literally.

Implements: REQ-SI-INV-004, REQ-SI-FR-004 (ADR-003, ADR-005)
"""

import json

from stockinsider.agent.registry import Registry, register_data_tools
from stockinsider.data import open_data_store
from stockinsider.data.store.resolver import SymbolResolver
from stockinsider.shared.tools import ToolCall

TENCENT_BODY = json.dumps(
    [
        {"Code": "0700", "Exchange": "HK", "Name": "TENCENT HOLDINGS LTD", "Type": "Common Stock"},
        {"Code": "0700", "Exchange": "US", "Name": "0700 METRIC LP", "Type": "Common Stock"},
    ]
)


def _registry(tmp_path) -> tuple[Registry, "object"]:
    ds = open_data_store(tmp_path / "data")
    ds.resolver = SymbolResolver(transport=lambda url, params: TENCENT_BODY, api_key="test-key")
    registry = Registry()
    register_data_tools(registry, ds)
    return registry, ds


def _add(registry: Registry, symbol: str, confirmed: bool | None = True, allow_write: bool = True):
    arguments: dict = {"canonical_symbol": symbol}
    if confirmed is not None:
        arguments["user_confirmed"] = confirmed
    return registry.execute(ToolCall(tool="watchlist.add", arguments=arguments, call_id="t"), allow_write=allow_write)


def test_fabricated_ticker_never_added(tmp_path) -> None:
    registry, ds = _registry(tmp_path)
    result = _add(registry, "FAKE.US", confirmed=True)
    assert result.ok is False and "no verified resolution record" in result.error
    assert ds.watchlist.active_count() == 0
    ds.close()


def test_tool_refuses_without_confirmation_flag(tmp_path) -> None:
    registry, ds = _registry(tmp_path)
    search = registry.execute(ToolCall(tool="symbol.search", arguments={"query": "Tencent Holdings"}, call_id="t"))
    assert search.ok and search.result[0]["canonical_symbol"] == "0700.HK"
    missing = _add(registry, "0700.HK", confirmed=None)  # arg absent -> schema rejection
    assert missing.ok is False and "user_confirmed" in missing.error
    refused = _add(registry, "0700.HK", confirmed=False)
    assert refused.ok is False and "confirmation" in refused.error
    assert ds.watchlist.active_count() == 0
    ds.close()


def test_write_gate_blocks_unconfirmed_calls(tmp_path) -> None:
    registry, ds = _registry(tmp_path)
    blocked = registry.execute(
        ToolCall(
            tool="watchlist.add",
            arguments={"canonical_symbol": "0700.HK", "user_confirmed": False},
            call_id="t",
        ),
        allow_write=False,
    )
    assert blocked.ok is False and "write effects" in blocked.error
    assert ds.watchlist.active_count() == 0
    ds.close()


def test_wrong_exchange_collision_presented_not_picked(tmp_path) -> None:
    registry, ds = _registry(tmp_path)
    search = registry.execute(ToolCall(tool="symbol.search", arguments={"query": "Tencent Holdings"}, call_id="t"))
    symbols = [cand["canonical_symbol"] for cand in search.result]
    assert symbols == ["0700.HK", "0700.US"]  # both presented, never auto-picked
    assert ds.watchlist.active_count() == 0  # nothing entered without the gate
    unconfirmed = _add(registry, "0700.US", confirmed=False)
    assert unconfirmed.ok is False  # no confirmation -> refused, even with a verified record
    right = _add(registry, "0700.HK", confirmed=True)  # the confirmed, verified path passes
    assert right.ok and ds.watchlist.active_count() == 1
    ds.close()


def test_seed_indices_resolvable_unaddable(tmp_path) -> None:
    registry, ds = _registry(tmp_path)
    search = registry.execute(ToolCall(tool="symbol.search", arguments={"query": "Hang Seng Index"}, call_id="t"))
    assert search.ok and search.result[0]["canonical_symbol"] == "HSI.INDX"
    result = _add(registry, "HSI.INDX", confirmed=True)
    assert result.ok is False and "benchmark" in result.error
    assert ds.watchlist.active_count() == 0
    ds.close()
