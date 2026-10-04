"""DE-14 (TP-029): an interrupted turn is marked incomplete and left out of replay.

Offline: a scripted provider drives the real turn engine and session store.
A KeyboardInterrupt stands in for Ctrl+C in the middle of a turn.

Implements: REQ-SI-FR-011, REQ-SI-FR-023, REQ-SI-INV-003 (ADR-001 Am2, ADR-004 Am5; TP-029)
"""

import json
from pathlib import Path

import pytest

from stockinsider.agent.loop import TurnEngine
from stockinsider.agent.providers import ChatOutcome
from stockinsider.agent.repl import build_registry, render_session
from stockinsider.agent.session import SessionStore
from stockinsider.shared.events import EventKind, EventValidationError, validate_event
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


class InterruptingProvider(ScriptedProvider):
    """Scripted provider whose call number `interrupt_on` raises KeyboardInterrupt."""

    def __init__(self, outcomes: list[ChatOutcome], interrupt_on: int) -> None:
        super().__init__(outcomes)
        self._interrupt_on = interrupt_on
        self._calls = 0

    def complete(self, messages, *, tools=None, stream_sink=None):
        self._calls += 1
        if self._calls == self._interrupt_on:
            self.seen_messages.append(list(messages))
            raise KeyboardInterrupt
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
    return [
        (event["event"], event.get("turn")) for event in store.read_events(session_id) if event["event"] in TURN_KINDS
    ]


def replayed_contents(provider: ScriptedProvider, call_index: int) -> list[str]:
    return [message.get("content") for message in provider.seen_messages[call_index]]


def test_interrupted_turn_is_marked_incomplete(store, prompts_dir) -> None:
    session_id = open_session(store)
    engine = engine_for(store, InterruptingProvider([], interrupt_on=1), prompts_dir)
    with pytest.raises(KeyboardInterrupt):
        run(engine, session_id, "What is the closing price of 0700.HK?")
    assert turn_events(store, session_id) == [("user-message", "turn-0001"), ("turn-incomplete", "turn-0001")]


def test_next_turn_does_not_replay_interrupted_question(store, prompts_dir) -> None:
    session_id = open_session(store)
    provider = InterruptingProvider([ChatOutcome(text="Understood.", usage={})], interrupt_on=1)
    engine = engine_for(store, provider, prompts_dir)
    with pytest.raises(KeyboardInterrupt):
        run(engine, session_id, "INTERRUPTED QUESTION")
    run(engine, session_id, "NEXT QUESTION")
    replayed = replayed_contents(provider, -1)
    assert "NEXT QUESTION" in replayed
    assert "INTERRUPTED QUESTION" not in replayed


def test_interrupt_after_answer_keeps_completed_turn(store, prompts_dir, monkeypatch) -> None:
    session_id = open_session(store)
    engine = engine_for(store, ScriptedProvider([ChatOutcome(text="Understood.", usage={})]), prompts_dir)

    def interrupt_after_answer(_verdict) -> None:
        raise KeyboardInterrupt

    # post-check counting runs after the answer is appended, so the interrupt lands after the answer
    monkeypatch.setattr(engine._counter, "record", interrupt_after_answer)
    with pytest.raises(KeyboardInterrupt):
        run(engine, session_id, "First question")
    assert turn_events(store, session_id) == [("user-message", "turn-0001"), ("assistant-message", "turn-0001")]

    provider = ScriptedProvider([ChatOutcome(text="Still here.", usage={})])
    run(engine_for(store, provider, prompts_dir), session_id, "Second question")
    replayed = replayed_contents(provider, 0)
    assert "First question" in replayed
    assert "Understood." in replayed


def test_answered_turn_is_never_left_out_even_with_marker(store, prompts_dir) -> None:
    session_id = open_session(store)
    store.append_event(session_id, {"event": "user-message", "text": "Kept question", "turn": "turn-0001"})
    store.append_event(session_id, {"event": "assistant-message", "text": "Kept answer.", "turn": "turn-0001"})
    store.append_event(session_id, {"event": "turn-incomplete", "turn": "turn-0001"})
    provider = ScriptedProvider([ChatOutcome(text="Next answer.", usage={})])
    run(engine_for(store, provider, prompts_dir), session_id, "Next question")
    replayed = replayed_contents(provider, 0)
    assert "Kept question" in replayed
    assert "Kept answer." in replayed


def test_interrupt_during_tool_loop_is_marked(store, prompts_dir) -> None:
    session_id = open_session(store)
    provider = InterruptingProvider(
        [
            ChatOutcome(tool_calls=[tool_call("budget.query", {"profile": "quick"})], usage={}),
            ChatOutcome(text="Next.", usage={}),
        ],
        interrupt_on=2,
    )
    engine = engine_for(store, provider, prompts_dir)
    with pytest.raises(KeyboardInterrupt):
        run(engine, session_id, "What is my budget?")
    kinds_of_turn = [event["event"] for event in store.read_events(session_id) if event.get("turn") == "turn-0001"]
    assert "tool-call" in kinds_of_turn
    assert "tool-result" in kinds_of_turn
    assert turn_events(store, session_id) == [("user-message", "turn-0001"), ("turn-incomplete", "turn-0001")]

    run(engine, session_id, "Next question")
    replayed = replayed_contents(provider, -1)
    assert "Next question" in replayed
    assert "What is my budget?" not in replayed


def test_turn_incomplete_is_a_valid_event_kind(store) -> None:
    assert EventKind("turn-incomplete") is EventKind.TURN_INCOMPLETE
    validate_event({"event": "turn-incomplete", "turn": "turn-0001"})
    with pytest.raises(EventValidationError):
        validate_event({"event": "turn-incomplet", "turn": "turn-0001"})
    session_id = open_session(store)
    store.append_event(session_id, {"event": "turn-incomplete", "turn": "turn-0001"})
    assert store.read_events(session_id)[-1] == {"event": "turn-incomplete", "turn": "turn-0001"}


def test_transcript_shows_incomplete_turn(store, prompts_dir) -> None:
    session_id = open_session(store)
    engine = engine_for(store, InterruptingProvider([], interrupt_on=1), prompts_dir)
    with pytest.raises(KeyboardInterrupt):
        run(engine, session_id, "Interrupted question")
    lines: list[str] = []
    render_session(store, session_id, lines.append)
    assert any("Interrupted question" in line for line in lines)
    assert any("incomplete no answer recorded" in line for line in lines)
