"""Offline tests for the FR-013 CLI surface scaffold (TP-001).

Covers: package metadata, the nine-subcommand help surface, the version
flag, and the negative test that every stub fails explicitly (non-zero
exit, "not implemented" message naming its target requirement) — the
adversarial guard against stubs silently pretending success.
"""

import stockinsider
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
    for name in SUBCOMMANDS:
        result = runner.invoke(app, [name] + STUB_ARGS.get(name, []))
        combined = result.output + (result.stderr or "")
        assert result.exit_code != 0, f"{name}: stub must not exit 0"
        assert "not implemented" in combined, f"{name}: explicit failure message missing"
        assert "REQ-SI-" in combined, f"{name}: message must name its target requirement"
