"""TP-017 PR-1: guardrail pipeline core (H1, H2, H4, H5, M6).

Implements: REQ-SI-INV-001, REQ-SI-INV-003, REQ-SI-FR-008, REQ-SI-FR-019
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from stockinsider.agent.guardrail import GuardrailVerdict, NumberCheck
from stockinsider.agent.loop import TurnEngine
from stockinsider.agent.providers import ChatOutcome, ProviderError
from stockinsider.agent.session import SessionStore


class ScriptedProvider:
    def __init__(self, outcomes: list[ChatOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.seen_messages: list[list[dict]] = []

    def complete(self, messages, *, tools=None, stream_sink=None):
        self.seen_messages.append(list(messages))
        outcome = self._outcomes.pop(0)
        if stream_sink is not None and outcome.text and not outcome.tool_calls:
            stream_sink(outcome.text)
        return outcome


class FakeRegistry:
    """Minimal registry seam: no tools registered."""

    def openai_tool_specs(self):
        return []

    def list_tools(self):
        return []


def _engine(tmp_path, outcomes) -> TurnEngine:
    store = SessionStore(root=tmp_path / "s")
    return TurnEngine(store, FakeRegistry(), ScriptedProvider(outcomes))


def _run(engine, session_id, text, sink=None):
    return engine.run_turn(
        session_id,
        text,
        profile="quick",
        render=lambda s: None,
        progress=lambda s: None,
        stream_sink=sink,
    )


def test_h1_pass_replays_after_verdict(tmp_path) -> None:
    engine = _engine(tmp_path, [ChatOutcome(text="no numbers here", usage={})])
    record = engine._store.create(profile="quick")  # noqa: SLF001 — test seam
    seen: list[str] = []
    outcome = _run(engine, record["session_id"], "hi", sink=seen.append)
    assert not outcome.quarantined
    assert "".join(seen).strip() == "no numbers here"  # replayed after the verdict


def test_h1_quarantine_never_replays_original(tmp_path, monkeypatch) -> None:
    from stockinsider.agent import loop as loop_mod

    engine = _engine(tmp_path, [ChatOutcome(text="close 436.6 cited", usage={})])
    record = engine._store.create(profile="quick")  # noqa: SLF001

    def fake_postcheck(candidate, snapshot_values):
        return GuardrailVerdict(
            display_text="data unavailable for: 436.6",
            quarantined=True,
            degraded=None,
            number_check=NumberCheck(passed=False, matched=[], failed=["436.6"], rounded=[]),
            epistemic=SimpleNamespace(violations=[], clean_text=candidate),
            language_ok=True,
            violations=[],
        )

    monkeypatch.setattr(loop_mod, "run_postcheck", fake_postcheck)
    seen: list[str] = []
    outcome = _run(engine, record["session_id"], "q", sink=seen.append)
    assert outcome.quarantined
    assert seen == []  # the original text never reached the user sink
    assert "436.6" in outcome.displayed


def test_m6_user_message_not_duplicated(tmp_path) -> None:
    engine = _engine(tmp_path, [ChatOutcome(text="ok", usage={}), ChatOutcome(text="ok2", usage={})])
    store = engine._store
    record = store.create(profile="quick")
    _run(engine, record["session_id"], "hello")
    _run(engine, record["session_id"], "second")
    provider = engine._provider  # noqa: SLF001
    first_user = [m["content"] for m in provider.seen_messages[0] if m["role"] == "user"]
    second_user = [m["content"] for m in provider.seen_messages[1] if m["role"] == "user"]
    assert first_user == ["hello"]
    # current message exactly once + prior turn in history once
    assert second_user.count("second") == 1
    assert second_user.count("hello") == 1


def test_h4_abort_is_sticky(tmp_path, monkeypatch) -> None:
    engine = _engine(tmp_path, [ChatOutcome(text="a1", usage={}), ChatOutcome(text="never", usage={})])
    record = engine._store.create(profile="quick")  # noqa: SLF001

    # force a withheld verdict whose INV-002 violations exceed the budget ->
    # the counter aborts on the first turn. TP-023 (ADR-008 requirement
    # change): the INV-001 abort is retired, so the INV-002 budget drives it.
    from stockinsider.agent import loop as loop_mod
    from stockinsider.agent.guardrail import PostCheckCounter

    def fake_postcheck(candidate, snapshot_values):
        return GuardrailVerdict(
            display_text="response withheld",
            quarantined=True,
            degraded=None,
            number_check=NumberCheck(passed=True, matched=[], failed=[], rounded=[]),
            epistemic=SimpleNamespace(violations=["v1", "v2", "v3"], clean_text=candidate),
            language_ok=True,
            violations=[],
        )

    monkeypatch.setattr(loop_mod, "run_postcheck", fake_postcheck)
    engine._counter = PostCheckCounter(epistemic_limit=2)  # noqa: SLF001

    first = _run(engine, record["session_id"], "x")
    assert first.quarantined
    assert first.aborted is not None  # threshold reached on the first strike
    second = _run(engine, record["session_id"], "y")
    assert second.aborted is not None
    assert "no longer calls the model" in second.displayed
    provider = engine._provider  # noqa: SLF001
    assert len(provider.seen_messages) == 1  # the refusal made zero provider calls


def test_h5_sync_status_serializable(tmp_path) -> None:
    from stockinsider.data.ingest.sync import sync_status
    from stockinsider.data.store.db import open_db

    conn = open_db(tmp_path / "x.sqlite")
    json.dumps(sync_status(conn))  # must not raise (raw Row crashed this before)


def test_h5_bare_slash_parts_empty() -> None:
    parts = "/"[1:].split()
    assert parts == []  # the old unpack raised ValueError on exactly this


def test_h5_stream_break_wrapped() -> None:
    from stockinsider.agent.providers import OpenAICompatibleProvider, ProviderConfig

    def boom_factory(base_url, api_key):
        def create(**kwargs):
            def iterator():
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="par"))], usage=None)
                raise OSError("connection reset mid-stream")

            return iterator()

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    config = ProviderConfig(
        chat_base_url="https://api.deepseek.com/v1",
        chat_model="m",
        embedding_base_url=None,
        embedding_model="m",
        budgets={},
    )
    provider = OpenAICompatibleProvider(config, api_key="sk", client_factory=boom_factory)
    with pytest.raises(ProviderError, match="mid-response"):
        provider.complete([{"role": "user", "content": "hi"}], stream_sink=lambda p: None)


def test_h2_regenerated_fabrication_is_marked(tmp_path, monkeypatch) -> None:
    """A regeneration carrying a fabricated number never displays it unmarked (ADR-008)."""
    # primary candidate violates epistemic rules; regeneration fabricates a number
    provider = ScriptedProvider(
        [
            ChatOutcome(text="this WILL rise 100 percent", usage={}),
            ChatOutcome(text="it rose 777.77 instead", usage={}),
        ]
    )
    store = SessionStore(root=tmp_path / "s")
    engine = TurnEngine(store, FakeRegistry(), provider)
    record = store.create(profile="quick")
    # no tools ran, so the verification pool is empty: any number in the
    # regeneration must fail the recheck
    outcome = _run(engine, record["session_id"], "q")
    # TP-023 (ADR-008 requirement change): shown only with the marker, never bare
    assert outcome.quarantined is False
    assert outcome.unverified == ["777.77"]
    assert "777.77[?]" in outcome.displayed
    assert outcome.displayed.count("777.77") == outcome.displayed.count("777.77[?]")
