"""TP-017 PR-2: write-tool confirmation tokens (H3, INV-004).

Implements: REQ-SI-INV-004, REQ-SI-FR-004 (ADR-005 Am1)
"""

from __future__ import annotations

import json

from stockinsider.agent.confirm import ConfirmationBroker
from stockinsider.agent.loop import TurnEngine
from stockinsider.agent.registry import Registry, register_data_tools, register_sync_tools
from stockinsider.agent.session import SessionStore
from stockinsider.shared.tools import ToolCall


class _FakeWatch:
    def add_verified(self, symbol, *, user_confirmed, via):
        assert user_confirmed is True
        return {"status": "active", "canonical_symbol": symbol, "via": via}

    def remove(self, symbol):
        return {"status": "removed", "canonical_symbol": symbol}

    def list(self):
        return []


class _FakeResolver:
    def search(self, query):
        return []


class _FakeStore:
    resolver = _FakeResolver()
    watchlist = _FakeWatch()

    def run_sync(self, progress=None):
        return {"counts": {"ok": 0, "failed": 0, "deferred": 0}}

    def sync_status(self):
        return {"budget": {"remaining": 1}}


def _registry_with_writes() -> Registry:
    registry = Registry()
    register_data_tools(registry, _FakeStore())
    register_sync_tools(registry, _FakeStore())
    return registry


def test_broker_tokens_are_single_use() -> None:
    broker = ConfirmationBroker()
    token = broker.issue("s1", "watchlist.add", {"canonical_symbol": "0700.HK"})
    first = broker.consume(token)
    assert first is not None and first.tool == "watchlist.add"
    assert broker.consume(token) is None  # consumed: never again


def test_broker_expiry_drops_stale() -> None:
    broker = ConfirmationBroker()
    token = broker.issue("s1", "sync.run", {}, turn=1)
    broker.expire_turns(current_turn=10, max_age=3)
    assert broker.consume(token) is None


def test_model_cannot_execute_write_via_boolean() -> None:
    """The old hole: user_confirmed=true filled by the model."""
    registry = _registry_with_writes()
    result = registry.execute(
        ToolCall(
            tool="watchlist.add",
            arguments={"canonical_symbol": "0700.HK", "user_confirmed": True},
            call_id="t1",
        )
    )
    assert result.ok is False  # unknown argument user_confirmed rejected at validation


def test_write_gate_requires_allow_write() -> None:
    registry = _registry_with_writes()
    blocked = registry.execute(ToolCall(tool="sync.run", arguments={}, call_id="t2"), allow_write=False)
    assert blocked.ok is False and "write" in (blocked.error or "").lower()
    allowed = registry.execute(ToolCall(tool="sync.run", arguments={}, call_id="t3"), allow_write=True)
    assert allowed.ok, allowed.error


def test_loop_intercepts_writes_and_issues_token(tmp_path) -> None:
    """A model write-call never executes; a token is issued and relayed."""
    provider_calls = {
        "tool": {
            "id": "c1",
            "type": "function",
            "function": {"name": "watchlist_add", "arguments": json.dumps({"canonical_symbol": "0700.HK"})},
        }
    }
    from stockinsider.agent.providers import ChatOutcome as Outcome

    class Provider:
        def __init__(self):
            self.messages = []

        def complete(self, messages, *, tools=None, stream_sink=None):
            self.messages.append(list(messages))
            if len(self.messages) == 1:
                return Outcome(tool_calls=[provider_calls["tool"]], usage={})
            return Outcome(text="please confirm the token above", usage={})

    store = SessionStore(root=tmp_path / "s")
    engine = TurnEngine(store, _registry_with_writes(), Provider())
    record = store.create(profile="quick")
    outcome = engine.run_turn(
        record["session_id"],
        "add tencent",
        profile="quick",
        render=lambda s: None,
        progress=lambda s: None,
    )
    assert not outcome.quarantined
    # a token was issued and stays pending until the human redeems it
    engine.confirmations._pending  # noqa: SLF001 — existence check
    pending = list(engine.confirmations._pending.values())  # noqa: SLF001
    assert len(pending) == 1 and pending[0].tool == "watchlist.add"
    # the tool message the model saw explains the protocol
    tool_msgs = [m for m in engine._provider.messages[1] if m.get("role") == "tool"]  # noqa: SLF001
    assert tool_msgs and "confirmation required" in tool_msgs[0]["content"]


def test_confirmed_replay_executes_and_records(tmp_path) -> None:
    registry = _registry_with_writes()
    store = SessionStore(root=tmp_path / "s")
    engine = TurnEngine(store, registry, provider=object())
    record = store.create(profile="quick")
    token = engine.confirmations.issue(record["session_id"], "watchlist.add", {"canonical_symbol": "0700.HK"})
    pending = engine.confirmations.consume(token)
    assert pending is not None
    result = registry.execute(
        ToolCall(tool=pending.tool, arguments=pending.arguments, call_id=f"confirm-{token}"),
        allow_write=True,
    )
    assert result.ok, result.error
    assert result.result["via"] == "agent-tool"
