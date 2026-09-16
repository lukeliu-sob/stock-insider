"""Typer application: FR-013 subcommand surface (scaffold stubs).

All nine subcommands are registered but intentionally not implemented:
each exits non-zero with an explicit English "not implemented" message
naming its target requirement — refuse to pretend success (INV-003
semantics). Real behavior lands per command in later test-planned
changes; the interactive REPL is likewise deferred to the agent-runtime
test plan.

Implements: REQ-SI-FR-013, REQ-SI-INV-003 (ADR-001)
"""

from typing import NoReturn

import typer

from stockinsider import __version__

app = typer.Typer(
    name="stockinsider",
    help="Local CLI financial analyst for HK + US equities (analysis only; never trades).",
    no_args_is_help=True,
)

_STUB_NOTE = "error: '{command}' is not implemented yet (target: {req}); refusing to pretend success (INV-003)."


def _stub(command: str, req: str) -> NoReturn:
    """Emit the explicit not-implemented failure and exit non-zero."""
    typer.secho(_STUB_NOTE.format(command=command, req=req), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2)


@app.command()
def sync() -> None:
    """Ingest daily EOD market data, fundamentals, and news (idempotent).

    Implements: REQ-SI-FR-001
    """
    _stub("sync", "REQ-SI-FR-001")


@app.command()
def watch() -> None:
    """Manage the watchlist (add/remove/list; verified symbol resolution).

    Implements: REQ-SI-FR-004
    """
    _stub("watch", "REQ-SI-FR-004")


@app.command()
def info(symbol: str = typer.Argument(..., help="Canonical symbol, e.g. 0700.HK")) -> None:
    """Display the current basic information snapshot for a symbol.

    Implements: REQ-SI-FR-005
    """
    _stub("info", "REQ-SI-FR-005")


@app.command()
def analyze() -> None:
    """Produce an analysis report for a symbol or topic (interactive only).

    Implements: REQ-SI-FR-008
    """
    _stub("analyze", "REQ-SI-FR-008")


@app.command()
def resume() -> None:
    """Resume a closed session (default: the most recent).

    Implements: REQ-SI-FR-023
    """
    _stub("resume", "REQ-SI-FR-023")


@app.command()
def sessions() -> None:
    """List sessions from the sessions index.

    Implements: REQ-SI-FR-012
    """
    _stub("sessions", "REQ-SI-FR-012")


@app.command()
def show() -> None:
    """Render a session for read-only review.

    Implements: REQ-SI-FR-022
    """
    _stub("show", "REQ-SI-FR-022")


@app.command()
def config() -> None:
    """Configure chat/embedding model endpoints (OpenAI-compatible).

    Implements: REQ-SI-FR-021
    """
    _stub("config", "REQ-SI-FR-021")


@app.command()
def digest() -> None:
    """Generate the weekly digest per watchlist symbol.

    Implements: REQ-SI-FR-016
    """
    _stub("digest", "REQ-SI-FR-016")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"stockinsider {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the version and exit.",
        callback=_print_version,
        is_eager=True,
    ),
) -> None:
    """Local CLI financial analyst for HK + US equities."""


def main() -> None:
    """Console-script entry point.

    Implements: REQ-SI-FR-013
    """
    app()
