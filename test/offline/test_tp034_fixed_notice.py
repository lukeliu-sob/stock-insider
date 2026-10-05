"""TP-034: a fixed reliability notice follows every answer (DE-09 residual, ADR-006 Am12).

The notice is display only. The tests check where it appears (on the progress channel,
directly after the footer of an answered turn) and where it must not appear: in the
rendered answer, in the session record, and in the model input of the next turn.

Offline: a scripted provider drives the real turn engine and session store.

Implements: REQ-SI-INV-002 (ADR-006; TP-034)
"""

import json
from pathlib import Path

import pytest

from stockinsider.agent.loop import AGENT_NOTICE, TurnEngine
from stockinsider.agent.providers import ChatOutcome
from stockinsider.agent.repl import build_registry
from stockinsider.agent.session import SessionStore
from test_streaming import ScriptedProvider

IDENTITY = """---
version: 1
artifact: identity
---

# Test identity

You are a test analyst.
"""

# No number and no prediction, so the post-check and the INV-002 filter both pass it.
ANSWER = "Analysis needs stored data before any view can be given."
USAGE = {"prompt_tokens": 5, "completion_tokens": 5}


@pytest.fixture()
def prompts_dir(tmp_path) -> Path:
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "identity.md").write_text(IDENTITY, encoding="utf-8")
    return directory


@pytest.fixture()
def store(tmp_path) -> SessionStore:
    return SessionStore(root=tmp_path / "sessions")


class Spy:
    def __init__(self) -> None:
        self.rendered: list[str] = []
        self.progressed: list[str] = []

    def render(self, text: str) -> None:
        self.rendered.append(text)

    def progress(self, text: str) -> None:
        self.progressed.append(text)

    def sink(self, piece: str) -> None:
        pass


def make_engine(store: SessionStore, provider: ScriptedProvider, prompts_dir: Path) -> TurnEngine:
    return TurnEngine(store, build_registry(store), provider, prompts_dir=prompts_dir)


def ask(engine: TurnEngine, session_id: str, question: str, spy: Spy):
    return engine.run_turn(
        session_id,
        question,
        profile="quick",
        render=spy.render,
        progress=spy.progress,
        stream_sink=spy.sink,
    )


def test_notice_follows_the_footer_of_an_answered_turn(store, prompts_dir) -> None:
    provider = ScriptedProvider([ChatOutcome(text=ANSWER, usage=USAGE)])
    engine = make_engine(store, provider, prompts_dir)
    record = store.create(profile="quick", provenance={"model_id": "m", "provider_config": "u"})
    spy = Spy()
    ask(engine, record["session_id"], "what is the plan?", spy)
    footer = next(index for index, line in enumerate(spy.progressed) if line.startswith("(tools: "))
    assert spy.progressed.count(AGENT_NOTICE) == 1
    assert spy.progressed.index(AGENT_NOTICE) == footer + 1


def test_notice_is_not_part_of_the_answer_or_the_session_record(store, prompts_dir) -> None:
    provider = ScriptedProvider([ChatOutcome(text=ANSWER, usage=USAGE)])
    engine = make_engine(store, provider, prompts_dir)
    record = store.create(profile="quick", provenance={"model_id": "m", "provider_config": "u"})
    spy = Spy()
    outcome = ask(engine, record["session_id"], "what is the plan?", spy)
    assert AGENT_NOTICE not in outcome.displayed
    assert all(AGENT_NOTICE not in text for text in spy.rendered)
    assert "probability machine" not in json.dumps(store.read_events(record["session_id"]))


def test_notice_stays_out_of_the_next_turns_model_input(store, prompts_dir) -> None:
    provider = ScriptedProvider(
        [ChatOutcome(text=ANSWER, usage=USAGE), ChatOutcome(text=ANSWER, usage=USAGE)]
    )
    engine = make_engine(store, provider, prompts_dir)
    record = store.create(profile="quick", provenance={"model_id": "m", "provider_config": "u"})
    spy = Spy()
    ask(engine, record["session_id"], "first question", spy)
    ask(engine, record["session_id"], "second question", spy)
    assert len(provider.seen_messages) == 2
    for messages in provider.seen_messages:
        assert "probability machine" not in json.dumps(messages)
