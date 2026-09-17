"""Session resume tests (TP-007b, FR-023).

Fit criteria: (a) prior session.jsonl content is byte-identical after
appended turns; (b) a resumed turn asking about a number absent from
the session context yields the degraded statement; profile lock and
status transitions per S1.
"""

import pytest

from stockinsider.agent.loop import TurnEngine
from stockinsider.agent.providers import ChatOutcome
from stockinsider.agent.repl import build_registry, resume_session
from stockinsider.agent.session import SessionError, SessionStore
from test_streaming import ScriptedProvider


class _Prompts:
    """Minimal prompts dir fixture via tmp_path; see conftest-free style."""

    @staticmethod
    def make(tmp_path):
        directory = tmp_path / "prompts"
        directory.mkdir(exist_ok=True)
        (directory / "identity.md").write_text("---\nversion: 1\nartifact: identity\n---\n\n# test\n", encoding="utf-8")
        return directory


@pytest.fixture()
def store(tmp_path) -> SessionStore:
    return SessionStore(root=tmp_path / "sessions")


def _seed_closed(store: SessionStore) -> str:
    record = store.create(
        profile="standard",
        provenance={"model_id": "m", "provider_config": "u", "prompt_version": "identity-v1"},
    )
    sid = record["session_id"]
    store.append_event(sid, {"event": "user-message", "text": "hi", "turn": "turn-0001"})
    store.append_event(
        sid,
        {"event": "assistant-message", "text": "hello", "turn": "turn-0001", "post_check": "ok", "usage": {}},
    )
    store.snapshot(sid, "turn-0001", {})
    store.close(sid)
    return sid


def test_prior_bytes_identical_after_appended_turn(store, tmp_path) -> None:
    sid = _seed_closed(store)
    stream = store.root / sid / "session.jsonl"
    before = stream.read_bytes()
    store.resume(sid)
    store.append_event(sid, {"event": "user-message", "text": "again", "turn": "turn-0002"})
    after = stream.read_bytes()
    assert after.startswith(before)
    assert b"again" in after[len(before) :]


def test_resumed_engine_restores_history_and_degrades_absent_numbers(store, tmp_path) -> None:
    sid = _seed_closed(store)
    store.resume(sid)
    prompts = _Prompts.make(tmp_path)
    engine = TurnEngine(
        store,
        build_registry(store),
        ScriptedProvider([ChatOutcome(text="sure, 777.", usage={})]),
        prompts_dir=prompts,
    )
    lines: list[str] = []
    outcome = engine.run_turn(
        sid,
        "what was that number?",
        profile="standard",
        render=lines.append,
        progress=lambda _p: None,
        stream_sink=lambda _s: None,
    )
    assert outcome.quarantined is True
    assert outcome.displayed == "data unavailable for: 777"
    provider = engine._provider  # noqa: SLF001 - white-box history assertion
    messages = provider.seen_messages[0]
    user_texts = [m["content"] for m in messages if m["role"] == "user"]
    assert "hi" in user_texts and "hello" in [m["content"] for m in messages if m["role"] == "assistant"]


def test_profile_lock_rejected_on_resume(store) -> None:
    sid = _seed_closed(store)
    with pytest.raises(SessionError, match="fixed for the session lifetime"):
        store.resume(sid, profile="deep")


def test_resume_session_loop_banner_and_close(store, tmp_path, monkeypatch) -> None:
    sid = _seed_closed(store)
    monkeypatch.setenv("STOCKINSIDER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("PROVIDER_API_KEY", raising=False)
    lines: list[str] = []
    resume_session(store, sid, input_fn=lambda _p: "/exit", echo=lines.append)
    joined = "\n".join(lines)
    assert f"session {sid} resumed" in joined
    assert "3 events restored" in joined  # session-open + user + assistant
    assert f"session {sid} closed" in joined
    assert store.list_sessions()[0]["status"] == "closed"


def test_resume_defaults_to_most_recent_closed(store) -> None:
    _first = _seed_closed(store)
    second = store.create(profile="deep")
    store.close(second["session_id"])
    lines: list[str] = []
    resume_session(store, None, data_root=None, input_fn=lambda _p: "/exit", echo=lines.append)
    assert any(second["session_id"] in line and "resumed" in line for line in lines)


def test_resume_with_no_closed_sessions_is_explicit(store) -> None:
    store.create(profile="standard")  # active, not closed
    with pytest.raises(SessionError, match="no closed session to resume"):
        resume_session(store, None, input_fn=lambda _p: "/exit", echo=lambda _l: None)
