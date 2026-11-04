"""TP-047: one fixed unverified notice, and a freshness sync when a session starts.

Implements: REQ-SI-INV-001, REQ-SI-FR-028, REQ-SI-INV-003 (ADR-008 Am6, ADR-002 Am3; TP-047)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from test_agent_loop import IDENTITY, Spy, make_engine
from typer.testing import CliRunner

from stockinsider.agent.loop import UNVERIFIED_NOTICE
from stockinsider.agent.providers import ChatOutcome
from stockinsider.agent.session import SessionStore
from stockinsider.cli import app as cli_app
from stockinsider.data import open_data_store
from stockinsider.data.ingest.freshness import behind, expected_session

runner = CliRunner()
NOTICE = "data with [?] means the data may be fabricated"


@pytest.fixture()
def prompts_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "identity.md").write_text(IDENTITY, encoding="utf-8")
    return directory


@pytest.fixture()
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(root=tmp_path / "sessions")


# -- the notice ------------------------------------------------------------------------


def _turn(engine: Any, record: dict[str, Any], question: str = "q") -> tuple[Any, Spy]:
    spy = Spy()
    outcome = engine.run_turn(
        record["session_id"], question, profile="standard", render=spy.render, progress=spy.progress,
        stream_sink=spy.sink,
    )
    return outcome, spy


def test_flagged_answer_shows_only_the_fixed_notice(store, prompts_dir) -> None:
    assert UNVERIFIED_NOTICE == NOTICE
    engine = make_engine(store, [ChatOutcome(text="The close was 999 and also 777.", usage={})], prompts_dir)
    record = store.create(profile="standard")
    outcome, spy = _turn(engine, record)
    assert outcome.displayed == "The close was 999[?] and also 777[?]."
    assert spy.lines.count(NOTICE) == 1
    # no number and no reason reaches the progress channel
    assert not any("999" in line or "777" in line for line in spy.lines)
    assert not any("evidence" in line or "not found" in line for line in spy.lines)


def test_reasons_stay_in_the_record(store, prompts_dir) -> None:
    engine = make_engine(store, [ChatOutcome(text="The close was 999.", usage={})], prompts_dir)
    record = store.create(profile="standard")
    _turn(engine, record)
    event = [e for e in store.read_events(record["session_id"]) if e["event"] == "assistant-message"][-1]
    assert event["post_check"] == "flagged"
    assert event["unverified"] == ["999"]
    assert event["unverified_detail"][0]["reason"] == "no close evidence"


def test_verified_answer_shows_no_notice(store, prompts_dir) -> None:
    engine = make_engine(store, [ChatOutcome(text="No numbers here.", usage={})], prompts_dir)
    record = store.create(profile="standard")
    _outcome, spy = _turn(engine, record)
    assert NOTICE not in spy.lines


def test_no_streak_notice_after_three_flagged_answers(store, prompts_dir) -> None:
    answers = [ChatOutcome(text=f"The answer is {900 + i}.", usage={}) for i in range(4)]
    engine = make_engine(store, answers, prompts_dir)
    record = store.create(profile="standard")
    spies = [_turn(engine, record, f"q{i}")[1] for i in range(4)]
    assert all(spy.lines.count(NOTICE) == 1 for spy in spies)
    assert not any("in a row" in line for spy in spies for line in spy.lines)


# -- freshness -------------------------------------------------------------------------


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def test_expected_session_by_exchange_and_time() -> None:
    # Wednesday 2026-11-04: HK available from 10:00 UTC, US from 23:00 UTC
    assert expected_session("HK", _utc("2026-11-04T09:59:59")) == date(2026, 11, 3)
    assert expected_session("HK", _utc("2026-11-04T10:00:00")) == date(2026, 11, 4)
    assert expected_session("US", _utc("2026-11-04T22:59:59")) == date(2026, 11, 3)
    assert expected_session("US", _utc("2026-11-04T23:00:00")) == date(2026, 11, 4)
    # Saturday, Sunday and Monday before availability map to Friday 2026-11-06
    for moment in ("2026-11-07T12:00:00", "2026-11-08T12:00:00", "2026-11-09T09:00:00"):
        assert expected_session("HK", _utc(moment)) == date(2026, 11, 6)
    assert expected_session("US", _utc("2026-11-09T22:00:00")) == date(2026, 11, 6)


def _seed(tmp_path, monkeypatch, newest: str, last_run: str | None) -> Any:
    """A store whose four benchmarks all end at `newest`, last synced at `last_run`."""
    monkeypatch.setenv("STOCKINSIDER_DATA_ROOT", str(tmp_path / "data"))
    data_store = open_data_store()
    conn = data_store.conn
    with conn:
        for symbol in ("HSI.INDX", "HSTECH.INDX", "GSPC.INDX", "NDX.INDX"):
            conn.execute(
                "INSERT INTO market_bars (canonical_symbol, date, close, currency, source, fetched_at)"
                " VALUES (?, ?, 1.0, 'POINTS', 'test', '2026-11-01T00:00:00+00:00')",
                (symbol, newest),
            )
            if last_run is not None:
                conn.execute(
                    "INSERT INTO sync_state (track, cursor, last_run_at, last_status) VALUES (?, ?, ?, 'ok')",
                    (f"market:{symbol}", newest, last_run),
                )
    return data_store


def test_behind_when_bar_older_and_no_run_since(tmp_path, monkeypatch) -> None:
    data_store = _seed(tmp_path, monkeypatch, "2026-11-03", "2026-11-04T02:00:00+00:00")
    rows = behind(data_store.conn, _utc("2026-11-04T11:00:00"))
    assert {row["symbol"] for row in rows} == {"HSI.INDX", "HSTECH.INDX"}  # US not yet available
    assert rows[0]["newest"] == "2026-11-03" and rows[0]["expected"] == "2026-11-04"
    data_store.close()


def test_not_behind_after_a_run_since_availability(tmp_path, monkeypatch) -> None:
    # a sync after the session became available found nothing newer (a holiday)
    data_store = _seed(tmp_path, monkeypatch, "2026-11-03", "2026-11-04T10:30:00+00:00")
    assert [r["symbol"] for r in behind(data_store.conn, _utc("2026-11-04T11:00:00"))] == []
    # boundary: a run one second before availability does not count
    with data_store.conn:
        data_store.conn.execute("UPDATE sync_state SET last_run_at = '2026-11-04T09:59:59+00:00'")
    assert len(behind(data_store.conn, _utc("2026-11-04T11:00:00"))) == 2
    data_store.close()


def test_not_behind_when_bar_is_current(tmp_path, monkeypatch) -> None:
    data_store = _seed(tmp_path, monkeypatch, "2026-11-04", None)
    assert behind(data_store.conn, _utc("2026-11-05T00:00:00")) == []
    data_store.close()


# -- the startup sync --------------------------------------------------------------------


class _FakeStore:
    def __init__(self, fresh: dict[str, Any]) -> None:
        self.fresh = fresh

    def freshness(self) -> dict[str, Any]:
        return self.fresh

    def close(self) -> None:
        pass


BEHIND = {"behind": [{"symbol": "0700.HK", "exchange": "HK", "newest": "2026-11-03", "expected": "2026-11-04"}],
          "market_live": True}


@pytest.fixture()
def calls(monkeypatch) -> list[str]:
    log: list[str] = []
    monkeypatch.setattr(cli_app, "_sync_and_report", lambda verbose=False: log.append("sync") or {})
    monkeypatch.setattr(cli_app, "_embed_and_report", lambda: log.append("embed") or {})
    monkeypatch.setattr(cli_app, "_interactive", lambda ui, **kwargs: log.append("session"))
    return log


def _use(monkeypatch, fresh: dict[str, Any]) -> None:
    monkeypatch.setattr(cli_app, "open_data_store", lambda: _FakeStore(fresh))


def test_startup_runs_sync_and_embed_when_behind(monkeypatch, calls) -> None:
    _use(monkeypatch, BEHIND)
    result = runner.invoke(cli_app.app, ["analyze"])
    assert result.exit_code == 0, result.output
    assert calls == ["sync", "embed", "session"]
    assert "data is behind (1 symbol(s), e.g. 0700.HK through 2026-11-03, expected 2026-11-04)" in result.output
    calls.clear()
    assert runner.invoke(cli_app.app, []).exit_code == 0  # bare invocation
    assert calls == ["sync", "embed", "session"]
    calls.clear()
    assert runner.invoke(cli_app.app, ["resume"]).exit_code == 0
    assert calls == ["sync", "embed", "session"]


def test_startup_skips_when_fresh(monkeypatch, calls) -> None:
    _use(monkeypatch, {"behind": [], "market_live": True})
    result = runner.invoke(cli_app.app, ["analyze"])
    assert calls == ["session"]
    assert "behind" not in result.output


def test_no_sync_flag_and_env_skip(monkeypatch, calls) -> None:
    _use(monkeypatch, BEHIND)
    runner.invoke(cli_app.app, ["analyze", "--no-sync"])
    runner.invoke(cli_app.app, ["--no-sync", "analyze"])
    runner.invoke(cli_app.app, ["analyze"], env={"STOCKINSIDER_NO_SYNC": "1"})
    assert calls == ["session", "session", "session"]


def test_startup_without_market_key_fetches_nothing(monkeypatch, calls) -> None:
    _use(monkeypatch, {**BEHIND, "market_live": False})
    result = runner.invoke(cli_app.app, ["analyze"])
    assert calls == ["session"]
    assert "automatic sync needs EODHD_API_KEY" in result.output


def test_sync_failure_still_opens_session(monkeypatch, calls) -> None:
    _use(monkeypatch, BEHIND)

    def _boom(verbose: bool = False) -> dict[str, Any]:
        raise RuntimeError("vendor down")

    monkeypatch.setattr(cli_app, "_sync_and_report", _boom)
    result = runner.invoke(cli_app.app, ["analyze"])
    assert result.exit_code == 0
    assert calls == ["session"]
    assert "automatic sync failed (RuntimeError: vendor down); continuing with the stored data" in result.output


def test_digest_runs_the_check(monkeypatch, calls) -> None:
    import stockinsider.agent.digest as digest_module

    stores: list[Any] = []

    def _open() -> Any:
        stores.append(_FakeStore(BEHIND))
        return stores[-1]

    monkeypatch.setattr(cli_app, "open_data_store", _open)

    class _Outcome:
        failed: list[str] = []

    monkeypatch.setattr(digest_module, "run_digest", lambda *args, **kwargs: calls.append("digest") or _Outcome())
    result = runner.invoke(cli_app.app, ["digest"])
    assert result.exit_code == 0, result.output
    assert calls == ["sync", "embed", "digest"]
