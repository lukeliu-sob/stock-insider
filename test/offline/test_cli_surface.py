"""Offline tests for the FR-013 CLI surface (TP-001 stubs, TP-002 REPL).

Covers: package metadata, the nine-subcommand help surface, the version
flag, explicit stub failures for not-yet-implemented commands, and —
since TP-002 — bare invocation and `analyze` entering the REPL, slash
dispatch, and the explicit free-text failure (INV-003).
"""

import stockinsider
import pytest
from stockinsider.cli.app import app
from typer.testing import CliRunner

SUBCOMMANDS = [
    "sync",
    "watch",
    "info",
    "analyze",
    "resume",
    "sessions",
    "show",
    "config",
    "digest",
]
#: Commands still explicit-failure stubs after TP-002 (sessions and
#: analyze are real behavior now; the negative stub guard covers the rest).
STUB_SUBCOMMANDS = [name for name in SUBCOMMANDS if name not in ("sessions", "analyze")]
STUB_ARGS = {"info": ["0700.HK"]}

runner = CliRunner()


def test_package_metadata() -> None:
    assert isinstance(stockinsider.__version__, str)
    assert "." in stockinsider.__version__


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert stockinsider.__version__ in result.output


def test_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in SUBCOMMANDS:
        assert name in result.output, f"subcommand missing from --help: {name}"


def test_stub_commands_fail_explicitly() -> None:
    for name in STUB_SUBCOMMANDS:
        result = runner.invoke(app, [name] + STUB_ARGS.get(name, []))
        combined = result.output + (result.stderr or "")
        assert result.exit_code != 0, f"{name}: stub must not exit 0"
        assert "not implemented" in combined, f"{name}: explicit failure message missing"
        assert "REQ-SI-" in combined, f"{name}: message must name its target requirement"


@pytest.fixture()
def sessions_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKINSIDER_SESSIONS_ROOT", str(tmp_path / "sessions"))


def test_bare_invocation_enters_repl(sessions_root) -> None:
    result = runner.invoke(app, [], input="/exit\n")
    assert result.exit_code == 0
    assert "opened (profile: standard)" in result.output
    assert "closed" in result.output


def test_analyze_enters_repl(sessions_root) -> None:
    result = runner.invoke(app, ["analyze"], input="/exit\n")
    assert result.exit_code == 0
    assert "session" in result.output


def test_repl_slash_sessions(sessions_root) -> None:
    result = runner.invoke(app, [], input="/sessions\n/exit\n")
    assert result.exit_code == 0
    # The REPL's own session is open, so the listing shows exactly it.
    assert "active" in result.output
    assert "standard" in result.output


def test_repl_unknown_slash_is_explicit_error(sessions_root) -> None:
    result = runner.invoke(app, [], input="/bogus\n/exit\n")
    assert result.exit_code == 0
    assert "unknown command /bogus" in result.output


def test_repl_free_text_fails_explicitly(sessions_root) -> None:
    result = runner.invoke(app, [], input="what about 0700.HK?\n/exit\n")
    assert result.exit_code == 0
    assert "not implemented" in result.output
    assert "INV-003" in result.output
