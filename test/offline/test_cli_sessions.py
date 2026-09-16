"""Offline tests for the sessions listing command (TP-002, FR-012).

Fit criterion: with N seeded sessions, output lists exactly the
sessions matching the filter; phantom entries number 0.
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
    first = store.create(profile="quick", subject_symbols=["0700.HK"])
    second = store.create(profile="deep", subject_symbols=["AAPL"])
    third = store.create(profile="standard", subject_symbols=["0700.HK", "0005.HK"])
    return store, [first, second, third]


def test_sessions_lists_all(seeded) -> None:
    _store, records = seeded
    result = runner.invoke(app, ["sessions"])
    assert result.exit_code == 0
    for record in records:
        assert record["session_id"] in result.output


def test_sessions_filter_by_symbol(seeded) -> None:
    _store, records = seeded
    result = runner.invoke(app, ["sessions", "--symbol", "0700.HK"])
    assert result.exit_code == 0
    assert records[0]["session_id"] in result.output
    assert records[2]["session_id"] in result.output
    assert records[1]["session_id"] not in result.output


def test_sessions_no_match_is_explicit_empty(seeded) -> None:
    result = runner.invoke(app, ["sessions", "--symbol", "NOPE.X"])
    assert result.exit_code == 0
    assert "no sessions match the filter" in result.output
