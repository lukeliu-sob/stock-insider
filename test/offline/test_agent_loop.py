"""Agent turn-engine tests (TP-007a): the full §7.2 pipeline, offline.

Scripted providers drive real registries, stores, and the guardrail:
tool loops, values-as-seen snapshots, quarantine, regeneration,
iteration caps, usage accounting, prompt versioning, history window.
"""

import json
from pathlib import Path

import pytest

from stockinsider.agent.loop import HISTORY_WINDOW, TurnEngine, load_identity_prompt
from stockinsider.agent.providers import ChatOutcome
from test_streaming import ScriptedProvider

from stockinsider.agent.repl import build_registry
from stockinsider.agent.session import SessionStore

IDENTITY = """---
version: 1
artifact: identity
---

# Test identity

You are a test analyst.
"""


@pytest.fixture()
def prompts_dir(tmp_path) -> Path:
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "identity.md").write_text(IDENTITY, encoding="utf-8")
    return directory


@pytest.fixture()
def store(tmp_path) -> SessionStore:
    return SessionStore(root=tmp_path / "sessions")


def make_engine(store: SessionStore, outcomes: list[ChatOutcome], prompts_dir: Path) -> TurnEngine:
    return TurnEngine(store, build_registry(store), ScriptedProvider(outcomes), prompts_dir=prompts_dir)


def tool_call(name: str, arguments: dict) -> dict:
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class Spy:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.streamed: list[str] = []

    def render(self, text: str) -> None:
        self.lines.append(text)

    def progress(self, text: str) -> None:
        self.lines.append(text)

    def sink(self, piece: str) -> None:
        self.streamed.append(piece)


def test_prompt_version_loading(prompts_dir) -> None:
    version, body = load_identity_prompt(prompts_dir)
    assert version == "identity-v1"
    assert "test analyst" in body


def test_tool_loop_end_to_end(store, prompts_dir) -> None:
    engine = make_engine(
        store,
        [
            ChatOutcome(
                tool_calls=[tool_call("budget.query", {"profile": "quick"})],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            ),
            ChatOutcome(text="The quick budget is 30000 tokens.", usage={"prompt_tokens": 20, "completion_tokens": 8}),
        ],
        prompts_dir,
    )
    record = store.create(profile="quick", provenance={"model_id": "m", "provider_config": "u"})
    spy = Spy()
    outcome = engine.run_turn(
        record["session_id"],
        "what is my budget?",
        profile="quick",
        render=spy.render,
        progress=spy.progress,
        stream_sink=spy.sink,
    )
    assert outcome.tools_used == 1
    assert outcome.quarantined is False
    assert "30000" in outcome.displayed
    assert any("budget.query … ok (computed)" in line for line in spy.lines)
    assert any("(tools: 1 · post-check: pass · tokens: 43)" in line for line in spy.lines)
    snapshot_path = store.root / record["session_id"] / "context" / "turn-0001.json"
    assert snapshot_path.is_file()
    values = json.loads(snapshot_path.read_text(encoding="utf-8"))["values"]
    assert values["budget.query"]["max_session_tokens"] == 30000
    events = store.read_events(record["session_id"])
    kinds = [e["event"] for e in events]
    assert kinds == ["session-open", "user-message", "tool-call", "tool-result", "assistant-message"]
    assert events[-1]["usage"] == {"prompt_tokens": 30, "completion_tokens": 13}


def test_fabricated_number_quarantined(store, prompts_dir) -> None:
    engine = make_engine(store, [ChatOutcome(text="The answer is 999.", usage={})], prompts_dir)
    record = store.create(profile="standard")
    spy = Spy()
    outcome = engine.run_turn(
        record["session_id"],
        "tell me",
        profile="standard",
        render=spy.render,
        progress=spy.progress,
        stream_sink=spy.sink,
    )
    assert outcome.quarantined is True
    assert outcome.displayed == "data unavailable for: 999"
    events = store.read_events(record["session_id"])
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1
    assert error_events[0]["post_check"] == "failed"
    assert error_events[0]["original"] == "The answer is 999."


def test_epistemic_regeneration(store, prompts_dir) -> None:
    engine = make_engine(
        store,
        [
            ChatOutcome(text="It will surge.", usage={"prompt_tokens": 5, "completion_tokens": 2}),
            ChatOutcome(text="It might rise (hypothesis).", usage={"prompt_tokens": 7, "completion_tokens": 3}),
        ],
        prompts_dir,
    )
    record = store.create(profile="standard")
    spy = Spy()
    outcome = engine.run_turn(
        record["session_id"],
        "outlook?",
        profile="standard",
        render=spy.render,
        progress=spy.progress,
        stream_sink=spy.sink,
    )
    assert outcome.displayed == "It might rise (hypothesis)."
    assert outcome.usage == {"prompt_tokens": 12, "completion_tokens": 5}


def test_three_strikes_aborts(store, prompts_dir) -> None:
    record = store.create(profile="standard")
    spy = Spy()
    aborted = None
    engine = make_engine(
        store, [ChatOutcome(text="Number 404.", usage={}) for _ in range(3)], prompts_dir
    )
    for _ in range(3):
        outcome = engine.run_turn(
            record["session_id"],
            "again",
            profile="standard",
            render=spy.render,
            progress=spy.progress,
            stream_sink=spy.sink,
        )
        aborted = outcome.aborted
    assert aborted == "abort:number"
    assert any("session aborted: abort:number" in line for line in spy.lines)


def test_iteration_cap_per_profile(store, prompts_dir) -> None:
    endless = [ChatOutcome(tool_calls=[tool_call("budget.query", {"profile": "deep"})], usage={}) for _ in range(30)]
    engine = make_engine(store, endless, prompts_dir)
    record = store.create(profile="deep")
    spy = Spy()
    outcome = engine.run_turn(
        record["session_id"],
        "go",
        profile="deep",
        render=spy.render,
        progress=spy.progress,
        stream_sink=spy.sink,
    )
    assert outcome.tools_used == 20  # deep cap
    assert "iteration cap (20)" in outcome.displayed
    record2 = store.create(profile="quick")
    engine2 = make_engine(store, endless, prompts_dir)
    outcome2 = engine2.run_turn(
        record2["session_id"],
        "go",
        profile="quick",
        render=spy.render,
        progress=spy.progress,
        stream_sink=spy.sink,
    )
    assert outcome2.tools_used == 4  # quick cap


def test_history_window_bounded(store, prompts_dir) -> None:
    record = store.create(profile="standard")
    for i in range(15):
        store.append_event(record["session_id"], {"event": "user-message", "text": f"msg {i}"})
        store.append_event(record["session_id"], {"event": "assistant-message", "text": f"reply {i}"})
    engine = make_engine(store, [ChatOutcome(text="ok", usage={})], prompts_dir)
    spy = Spy()
    engine.run_turn(
        record["session_id"],
        "now",
        profile="standard",
        render=spy.render,
        progress=spy.progress,
        stream_sink=spy.sink,
    )
    provider = engine._provider  # noqa: SLF001 - white-box window assertion
    messages = provider.seen_messages[0]
    user_texts = [m["content"] for m in messages if m["role"] == "user"]
    assert len(user_texts) == HISTORY_WINDOW // 2 + 1  # windowed pairs + current
    assert messages[0]["role"] == "system"
    assert user_texts[-1] == "now"


def test_clean_text_streams_without_double_render(store, prompts_dir) -> None:
    engine = make_engine(store, [ChatOutcome(text="clean and safe", usage={})], prompts_dir)
    record = store.create(profile="standard")
    spy = Spy()
    engine.run_turn(
        record["session_id"],
        "hi",
        profile="standard",
        render=spy.render,
        progress=spy.progress,
        stream_sink=spy.sink,
    )
    assert "".join(spy.streamed).endswith("\n")
    rendered = [line for line in spy.lines if "clean and safe" in line]
    assert rendered == []  # streamed once, not re-rendered
