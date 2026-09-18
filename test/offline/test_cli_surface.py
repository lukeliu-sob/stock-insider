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
#: Commands still explicit-failure stubs after TP-003 (sessions, analyze,
#: and config are real behavior now; the negative stub guard covers the rest).
STUB_SUBCOMMANDS = [
    name for name in SUBCOMMANDS if name not in ("sessions", "analyze", "config", "show", "resume", "watch", "sync")
]
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


@pytest.fixture(autouse=True)
def data_root(tmp_path, monkeypatch):
    """Isolate the SQLite store AND the env-file lookup away from the live worktree."""
    monkeypatch.setenv("STOCKINSIDER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(tmp_path / "no-keys.env"))
    monkeypatch.delenv("EODHD_API_KEY", raising=False)


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
    # Since TP-007a: free text runs the agent pipeline when configured; without
    # a provider it fails explicitly with remediation (superseded wording kept
    # for the INV-003 intent).
    result = runner.invoke(app, [], input="what about 0700.HK?\n/exit\n")
    assert result.exit_code == 0
    assert "provider unconfigured" in result.output


def test_repl_tools_lists_registered_tools(sessions_root) -> None:
    result = runner.invoke(app, [], input="/tools\n/exit\n")
    assert result.exit_code == 0
    for name in ("budget.query", "session.list", "context.estimate"):
        assert name in result.output
    assert "[compute]" in result.output and "[read]" in result.output


def test_repl_tools_direct_invocation(sessions_root) -> None:
    result = runner.invoke(app, [], input="/tools budget.query profile=quick\n/exit\n")
    assert result.exit_code == 0
    assert "30000" in result.output
    assert "provenance: computed" in result.output


def test_repl_tools_bad_argument_value_fails_explicitly(sessions_root) -> None:
    result = runner.invoke(app, [], input="/tools budget.query profile=turbo\n/exit\n")
    assert result.exit_code == 0
    assert "error:" in result.output and "failed" in result.output


def test_repl_tools_malformed_argument_rejected(sessions_root) -> None:
    result = runner.invoke(app, [], input="/tools budget.query turbo\n/exit\n")
    assert result.exit_code == 0
    assert "malformed argument" in result.output


def test_repl_tools_unknown_tool_rejected(sessions_root) -> None:
    result = runner.invoke(app, [], input="/tools magic.wand\n/exit\n")
    assert result.exit_code == 0
    assert "unknown tool" in result.output


def test_repl_free_text_with_unconfigured_provider_is_explicit(sessions_root, monkeypatch) -> None:
    monkeypatch.delenv("PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("PROVIDER_BASE_URL", raising=False)
    result = runner.invoke(app, [], input="hello there\n/exit\n")
    assert result.exit_code == 0
    assert "provider unconfigured" in result.output
    assert "config set" in result.output


# -- watch (TP-008): real subcommand with INV-004 gating --------------------


def test_watch_help_renders() -> None:
    result = runner.invoke(app, ["watch", "--help"])
    assert result.exit_code == 0
    assert "list | add | remove" in result.output


def test_watch_list_empty() -> None:
    result = runner.invoke(app, ["watch", "list"])
    assert result.exit_code == 0
    assert "watchlist is empty" in result.output


def test_watch_add_requires_eodhd_key_or_fails_explicitly() -> None:
    result = runner.invoke(app, ["watch", "add", "Tencent"], env={"EODHD_API_KEY": ""})
    # Without a live search path the failure is explicit (INV-003), never a fake add.
    assert result.exit_code != 0
    assert "not configured" in result.output


def test_watch_remove_unknown_symbol_explicit() -> None:
    result = runner.invoke(app, ["watch", "remove", "9999.HK"])
    assert result.exit_code == 1
    assert "not on the watchlist" in result.output
