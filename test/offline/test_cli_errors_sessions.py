"""TP-015 PR-c: unified error channel + sessions filters/pagination.

Implements: REQ-SI-FR-013, REQ-SI-FR-012 (ADR-001)
"""

from __future__ import annotations

from stockinsider.cli.render import render_error


def test_render_error_plain_when_piped(monkeypatch) -> None:
    import io

    monkeypatch.setattr("sys.stdout", io.StringIO())  # not a tty
    assert render_error("boom") == "error: boom"


def test_render_error_panel_when_tty(monkeypatch, capsys) -> None:
    import io

    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdout", _Tty())
    assert render_error("boom") == ""  # panel path prints, returns empty


def test_sessions_status_and_limit_filters(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from stockinsider.agent.session import SessionStore
    from stockinsider.cli.app import app

    store = SessionStore(root=tmp_path)
    for _ in range(4):
        record = store.create(profile="standard")
        store.close(record["session_id"])
    fifth = store.create(profile="standard")  # stays open

    monkeypatch.setattr("stockinsider.cli.app.SessionStore", lambda: SessionStore(root=tmp_path))
    runner = CliRunner()

    result = runner.invoke(app, ["sessions", "--status", "active"])
    assert result.exit_code == 0
    assert fifth["session_id"] in result.output
    assert result.output.count("closed") == 0

    result_closed = runner.invoke(app, ["sessions", "--status", "closed"])
    assert result_closed.exit_code == 0
    assert result_closed.output.count("closed") == 4
    assert fifth["session_id"] not in result_closed.output

    result_limit = runner.invoke(app, ["sessions", "--limit", "2"])
    assert result_limit.exit_code == 0
    assert "showing the 2 most recent of 5" in result_limit.output
    assert len([ln for ln in result_limit.output.splitlines() if "Z-" in ln]) == 2


def test_repl_sessions_pagination(tmp_path) -> None:
    from stockinsider.agent.repl import _cmd_sessions
    from stockinsider.agent.session import SessionStore

    store = SessionStore(root=tmp_path)
    for _ in range(12):
        store.create(profile="standard")

    out: list[str] = []
    _cmd_sessions(store, [], out.append)
    assert any("page 1/2" in line for line in out)
    assert sum(1 for line in out if "Z-" in line) == 10

    out2: list[str] = []
    _cmd_sessions(store, ["2"], out2.append)
    assert any("page 2/2" in line for line in out2)
    assert sum(1 for line in out2 if "Z-" in line) == 2

    out3: list[str] = []
    _cmd_sessions(store, ["99"], out3.append)
    assert any("page 2/2" in line for line in out3)  # clamped


def test_cli_error_sites_use_render_error(tmp_path, monkeypatch) -> None:
    """One error channel: piped output keeps the historical text."""
    from typer.testing import CliRunner

    from stockinsider.cli.app import app

    runner = CliRunner()
    result = runner.invoke(app, ["show", "no-such-session-id"])
    assert result.exit_code != 0
    assert "error:" in (result.output + (result.stderr or ""))
