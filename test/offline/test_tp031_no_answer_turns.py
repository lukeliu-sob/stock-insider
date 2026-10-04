"""DE-14 residual (TP-031): a turn that ends without an answer is marked incomplete.

Two exits end a turn without an answer: a ProviderError escaping the turn, and the
tool-iteration cap. Both are recorded as turn-incomplete, so replay leaves their
question out, as TP-029 already does for an interrupted turn.

Offline: a scripted provider drives the real turn engine and session store.

Implements: REQ-SI-FR-011, REQ-SI-FR-023, REQ-SI-INV-003 (ADR-001 Am3, ADR-004 Am6; TP-031)
"""

import json
from pathlib import Path

import pytest

from stockinsider.agent.loop import TurnEngine
from stockinsider.agent.providers import ChatOutcome, ProviderError
from stockinsider.agent.repl import build_registry, render_session
from stockinsider.agent.session import SessionStore
from test_streaming import ScriptedProvider

IDENTITY = """---
version: 1
artifact: identity
---

# Test identity

You are a test analyst.
"""

TURN_KINDS = ("user-message", "assistant-message", "turn-incomplete")


@pytest.fixture()
def prompts_dir(tmp_path) -> Path:
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "identity.md").write_text(IDENTITY, encoding="utf-8")
    return directory


@pytest.fixture()
def store(tmp_path) -> SessionStore:
    return SessionStore(root=tmp_path / "sessions")


class FailOnCall(ScriptedProvider):
    """Scripted provider whose call number `fail_on` raises ProviderError (an explicit failure)."""

    def __init__(self, outcomes: list[ChatOutcome], fail_on: int) -> None:
        super().__init__(outcomes)
        self._fail_on = fail_on
        self._calls = 0

    def complete(self, messages, *, tools=None, stream_sink=None):
        self._calls += 1
        if self._calls == self._fail_on:
            self.seen_messages.append(list(messages))
            raise ProviderError("provider unreachable")
        return super().complete(messages, tools=tools, stream_sink=stream_sink)


def tool_call(name: str, arguments: dict) -> dict:
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _ignore(_text: str) -> None:
    return None


def open_session(store: SessionStore) -> str:
    return store.create(profile="quick", provenance={"model_id": "m", "provider_config": "u"})["session_id"]


def engine_for(store: SessionStore, provider, prompts_dir: Path) -> TurnEngine:
    return TurnEngine(store, build_registry(store), provider, prompts_dir=prompts_dir)


def run(engine: TurnEngine, session_id: str, text: str):
    return engine.run_turn(session_id, text, profile="quick", render=_ignore, progress=_ignore)


def turn_events(store: SessionStore, session_id: str) -> list[tuple[str, str]]:
    events = store.read_events(session_id)
    return [(event["event"], event.get("turn")) for event in events if event["event"] in TURN_KINDS]


def replayed_contents(provider: ScriptedProvider, call_index: int) -> list[str]:
    return [message.get("content") for message in provider.seen_messages[call_index]]


def endless_tool_calls() -> list[ChatOutcome]:
    return [ChatOutcome(tool_calls=[tool_call("budget.query", {"profile": "quick"})], usage={}) for _ in range(30)]


def test_provider_error_marks_turn_incomplete(store, prompts_dir) -> None:
    session_id = open_session(store)
    engine = engine_for(store, FailOnCall([], fail_on=1), prompts_dir)
    with pytest.raises(ProviderError):
        run(engine, session_id, "Will this fail?")
    assert turn_events(store, session_id) == [("user-message", "turn-0001"), ("turn-incomplete", "turn-0001")]


def test_next_turn_does_not_replay_failed_question(store, prompts_dir) -> None:
    session_id = open_session(store)
    provider = FailOnCall([ChatOutcome(text="Understood.", usage={})], fail_on=1)
    engine = engine_for(store, provider, prompts_dir)
    with pytest.raises(ProviderError):
        run(engine, session_id, "FAILED QUESTION")
    run(engine, session_id, "NEXT QUESTION")
    replayed = replayed_contents(provider, -1)
    assert "NEXT QUESTION" in replayed
    assert "FAILED QUESTION" not in replayed


def test_iteration_cap_marks_turn_incomplete(store, prompts_dir) -> None:
    session_id = open_session(store)
    engine = engine_for(store, ScriptedProvider(endless_tool_calls()), prompts_dir)
    outcome = run(engine, session_id, "Keep looking")
    assert outcome.tools_used == 4  # the quick cap, as in test_iteration_cap_per_profile
    kinds_of_turn = [event["event"] for event in store.read_events(session_id) if event.get("turn") == "turn-0001"]
    assert kinds_of_turn[-2:] == ["error", "turn-incomplete"]
    assert turn_events(store, session_id) == [("user-message", "turn-0001"), ("turn-incomplete", "turn-0001")]


def test_next_turn_does_not_replay_capped_question(store, prompts_dir) -> None:
    session_id = open_session(store)
    run(engine_for(store, ScriptedProvider(endless_tool_calls()), prompts_dir), session_id, "CAPPED QUESTION")
    provider = ScriptedProvider([ChatOutcome(text="Understood.", usage={})])
    run(engine_for(store, provider, prompts_dir), session_id, "NEXT QUESTION")
    replayed = replayed_contents(provider, 0)
    assert "NEXT QUESTION" in replayed
    assert "CAPPED QUESTION" not in replayed


def test_answered_turn_with_tool_calls_is_not_marked(store, prompts_dir) -> None:
    session_id = open_session(store)
    provider = ScriptedProvider(
        [
            ChatOutcome(tool_calls=[tool_call("budget.query", {"profile": "quick"})], usage={}),
            ChatOutcome(text="Your budget is set.", usage={}),
        ]
    )
    outcome = run(engine_for(store, provider, prompts_dir), session_id, "What is my budget?")
    assert outcome.tools_used == 1
    events = turn_events(store, session_id)
    assert ("assistant-message", "turn-0001") in events
    assert "turn-incomplete" not in [kind for kind, _turn in events]


def test_transcript_shows_no_answer_turn(store, prompts_dir) -> None:
    session_id = open_session(store)
    engine = engine_for(store, FailOnCall([], fail_on=1), prompts_dir)
    with pytest.raises(ProviderError):
        run(engine, session_id, "Will this fail?")
    lines: list[str] = []
    render_session(store, session_id, lines.append)
    assert any("incomplete no answer recorded; left out of context" in line for line in lines)
