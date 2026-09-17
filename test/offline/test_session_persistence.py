"""Offline tests for session persistence (TP-002, FR-011).

Covers: tree layout on creation, append-only semantics of
session.jsonl, never-overwrite refusal for artifacts and snapshots,
index integrity (phantom rows skipped), and profile validation.
"""

import json

import pytest

from stockinsider.agent.session import SessionError, SessionStore


@pytest.fixture()
def store(tmp_path):
    return SessionStore(root=tmp_path / "sessions")


def test_create_session_layout(store) -> None:
    record = store.create(profile="quick", subject_symbols=["0700.HK"])
    session_dir = store.root / record["session_id"]
    assert (session_dir / "session.jsonl").is_file()
    assert (session_dir / "artifacts").is_dir()
    assert (session_dir / "context").is_dir()
    first = json.loads((session_dir / "session.jsonl").read_text(encoding="utf-8"))
    assert first["event"] == "session-open"
    assert first["record"]["session_id"] == record["session_id"]
    rows = store.list_sessions()
    assert [row["session_id"] for row in rows] == [record["session_id"]]


def test_append_only_never_rewrites(store) -> None:
    record = store.create()
    stream = store.root / record["session_id"] / "session.jsonl"
    before = stream.read_bytes()
    store.append_event(record["session_id"], {"event": "user-message", "text": "hello"})
    after = stream.read_bytes()
    assert after.startswith(before)
    assert after[len(before) :].strip() != b""
    assert len(after) > len(before)


def test_artifacts_never_overwritten(store) -> None:
    record = store.create()
    store.artifact(record["session_id"], "turn-001-report.md", "# report v1")
    with pytest.raises(SessionError, match="never overwritten"):
        store.artifact(record["session_id"], "turn-001-report.md", "# report v2")


def test_snapshot_values_as_seen_no_rewrite(store) -> None:
    record = store.create()
    store.snapshot(record["session_id"], "turn-001", {"quote": {"close": 311.4}})
    with pytest.raises(SessionError, match="never rewritten"):
        store.snapshot(record["session_id"], "turn-001", {"quote": {"close": 311.5}})


def test_index_phantom_rows_skipped(store, tmp_path) -> None:
    real = store.create()
    rows = store._index_read()
    rows.append(
        {
            "session_id": "99999999T999999Z-deadbeef",
            "profile": "quick",
            "status": "active",
            "created": "2026-09-16T00:00:00+00:00",
            "last_active": "2026-09-16T00:00:00+00:00",
            "subject_symbols": [],
            "provenance": {},
        }
    )
    store._index_write(rows)
    listed = [row["session_id"] for row in store.list_sessions()]
    assert listed == [real["session_id"]]


def test_unknown_session_rejected(store) -> None:
    with pytest.raises(SessionError, match="unknown session"):
        store.append_event("20260101T000000Z-nope", {"event": "x"})


def test_invalid_profile_rejected(store) -> None:
    with pytest.raises(SessionError, match="unknown analysis profile"):
        store.create(profile="turbo")


def test_close_and_reopen(store) -> None:
    record = store.create()
    store.close(record["session_id"])
    assert store.list_sessions()[0]["status"] == "closed"
    store.resume(record["session_id"])
    assert store.list_sessions()[0]["status"] == "active"


# -- GOV-005 provenance stamps (TP-003) --------------------------------------


def test_provenance_stamps_from_resolved_values(store) -> None:
    record = store.create(
        profile="quick",
        provenance={"model_id": "my-model", "provider_config": "https://api.example.com/v1"},
    )
    assert record["provenance"]["model_id"] == "my-model"
    assert record["provenance"]["provider_config"] == "https://api.example.com/v1"
    # Unspecified fields keep their explicit placeholders (never blank).
    assert record["provenance"]["prompt_version"].startswith("unset-until")


def test_zero_missing_provenance_fields_across_sessions(store) -> None:
    stamp = {"model_id": "m", "provider_config": "u"}
    for index in range(3):
        store.create(profile=("quick", "standard", "deep")[index], provenance=stamp)
    for row in store.list_sessions():
        assert set(row["provenance"]) == {"model_id", "prompt_version", "provider_config"}
        assert all(str(value).strip() for value in row["provenance"].values())


def test_repl_stamps_resolved_config(tmp_path, monkeypatch) -> None:
    from stockinsider.agent.providers import save_config
    from stockinsider.agent.repl import repl

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("STOCKINSIDER_DATA_ROOT", str(data))
    save_config({"chat_base_url": "https://r.example/v1", "chat_model": "rm"}, data)
    store = SessionStore(root=tmp_path / "sessions")
    repl(store, input_fn=lambda _prompt: "/exit", echo=lambda _line: None)
    row = store.list_sessions()[0]
    assert row["provenance"]["model_id"] == "rm"
    assert row["provenance"]["provider_config"] == "https://r.example/v1"


# -- shared provenance + event schema adoption (TP-004) ----------------------


def test_provenance_stamp_roundtrip(store) -> None:
    from stockinsider.shared.provenance import ProvenanceStamp

    record = store.create(profile="quick", provenance={"model_id": "m", "provider_config": "u"})
    stamp = ProvenanceStamp.from_record(record["provenance"])
    assert stamp.model_id == "m"
    assert stamp.to_record()["model_id"] == "m"


def test_blank_provenance_value_rejected(store) -> None:
    with pytest.raises(Exception, match="non-empty string"):
        store.create(profile="quick", provenance={"model_id": "  "})


def test_non_string_provenance_rejected(store) -> None:
    with pytest.raises(Exception, match="non-empty string"):
        store.create(profile="quick", provenance={"model_id": 42})


def test_validate_event_replays_real_session_log(store) -> None:
    from stockinsider.shared.events import validate_event

    record = store.create(profile="standard")
    store.append_event(record["session_id"], {"event": "user-message", "text": "hello"})
    log = (store.root / record["session_id"] / "session.jsonl").read_text(encoding="utf-8")
    for line in log.splitlines():
        if line.strip():
            validate_event(json.loads(line))


def test_unknown_event_kind_rejected() -> None:
    from stockinsider.shared.events import EventValidationError, validate_event

    with pytest.raises(EventValidationError, match="unknown event kind"):
        validate_event({"event": "teleport"})


def test_session_open_without_record_rejected() -> None:
    from stockinsider.shared.events import EventValidationError, validate_event

    with pytest.raises(EventValidationError, match="record"):
        validate_event({"event": "session-open"})
