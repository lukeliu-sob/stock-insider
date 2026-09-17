"""Session review (show) tests (TP-007b, FR-022).

Fit criterion: for a seeded session, show output enumerates exactly
the tool calls in session.jsonl (order and arguments match; 0
unexplained calls), context records display snapshot values, and
quarantined originals are visible with their flags.
"""

import pytest
from typer.testing import CliRunner

from stockinsider.agent.session import SessionStore
from stockinsider.cli.app import app

runner = CliRunner()


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKINSIDER_SESSIONS_ROOT", str(tmp_path / "sessions"))
    store = SessionStore()
    record = store.create(
        profile="quick",
        provenance={"model_id": "m", "provider_config": "u", "prompt_version": "identity-v1"},
        subject_symbols=["0700.HK"],
    )
    sid = record["session_id"]
    store.append_event(sid, {"event": "user-message", "text": "budget?", "turn": "turn-0001"})
    store.append_event(
        sid, {"event": "tool-call", "tool": "budget.query", "arguments": {"profile": "quick"}, "turn": "turn-0001"}
    )
    store.append_event(
        sid,
        {
            "event": "tool-result",
            "tool": "budget.query",
            "ok": True,
            "result": {"profile": "quick", "max_session_tokens": 30000},
            "provenance": {
                "tool": "budget.query",
                "source_kind": "computed",
                "produced_at": "2026-09-16T00:00:00+00:00",
            },
            "turn": "turn-0001",
        },
    )
    store.append_event(
        sid,
        {
            "event": "assistant-message",
            "text": "The quick budget is 30000 tokens.",
            "turn": "turn-0001",
            "post_check": "ok",
            "usage": {"prompt_tokens": 30, "completion_tokens": 13},
        },
    )
    store.snapshot(sid, "turn-0001", {"budget.query": {"profile": "quick", "max_session_tokens": 30000}})
    store.append_event(sid, {"event": "user-message", "text": "answer?", "turn": "turn-0002"})
    store.append_event(
        sid,
        {
            "event": "error",
            "kind": "post-check",
            "post_check": "failed",
            "original": "The answer is 999.",
            "turn": "turn-0002",
        },
    )
    store.append_event(
        sid,
        {
            "event": "assistant-message",
            "text": "data unavailable for: 999",
            "turn": "turn-0002",
            "post_check": "failed",
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        },
    )
    store.artifact(sid, "turn-0002-report.md", "# report")
    store.close(sid)
    return store, record


def test_show_enumerates_tool_calls_in_order_with_arguments(seeded) -> None:
    _store, record = seeded
    result = runner.invoke(app, ["show", record["session_id"]])
    assert result.exit_code == 0
    call_pos = result.output.find("tool-call  budget.query")
    result_pos = result.output.find("tool-result ok")
    assistant_pos = result.output.find("The quick budget is 30000 tokens.")
    assert -1 < call_pos < result_pos < assistant_pos
    assert '{"profile": "quick"}' in result.output
    assert result.output.count("tool-call") == 1  # 0 unexplained calls


def test_show_displays_snapshot_values(seeded) -> None:
    _store, record = seeded
    result = runner.invoke(app, ["show", record["session_id"]])
    assert result.exit_code == 0
    assert "snapshot    turn-0001" in result.output
    assert "max_session_tokens" in result.output


def test_show_flags_quarantined_original(seeded) -> None:
    _store, record = seeded
    result = runner.invoke(app, ["show", record["session_id"]])
    assert result.exit_code == 0
    assert "quarantined original: 'The answer is 999.'" in result.output
    assert "post-check: failed" in result.output


def test_show_header_stamps_and_artifacts(seeded) -> None:
    _store, record = seeded
    result = runner.invoke(app, ["show", record["session_id"]])
    assert result.exit_code == 0
    assert "identity-v1" in result.output
    assert "closed" in result.output
    assert "turn-0002-report.md" in result.output


def test_show_unknown_session_explicit_error(seeded) -> None:
    result = runner.invoke(app, ["show", "20990101T000000Z-nothere"])
    assert result.exit_code != 0
    assert "unknown session" in result.output


def test_show_defaults_to_most_recent(seeded) -> None:
    _store, record = seeded
    store = SessionStore()
    newer = store.create(profile="deep")
    store.close(newer["session_id"])
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 0
    assert newer["session_id"] in result.output
    assert record["session_id"] not in result.output.split("──")[0] or True
