"""Typer application: FR-013 subcommand surface.

Six subcommands remain explicit-failure stubs (English error naming
the target requirement, non-zero exit — INV-003 semantics); `sessions`
lists from the sessions index (FR-012), `analyze` and bare invocation
enter the REPL (FR-013), and `config` shows/updates the layered
provider configuration (FR-021, SEC-001).

Implements: REQ-SI-FR-013, REQ-SI-INV-003 (ADR-001)
"""

from typing import NoReturn, Optional

import typer

from stockinsider import __version__
from stockinsider.agent.providers import (
    config_path,
    mask_key,
    resolve_api_key,
    resolve_config,
    save_config,
    write_env_api_key,
)
from stockinsider.agent.repl import render_session, repl, resume_session
from stockinsider.agent.session import SessionError, SessionStore
from stockinsider.data import (
    ResolverUnavailable,
    WatchlistError,
    open_data_store,
)

app = typer.Typer(
    name="stockinsider",
    help="Local CLI financial analyst for HK + US equities (analysis only; never trades).",
    no_args_is_help=False,
    invoke_without_command=True,
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
def watch(
    action: str = typer.Argument("list", help="list | add | remove"),
    query: Optional[str] = typer.Argument(None, help="mention/name for add; canonical symbol for remove"),
) -> None:
    """Manage the watchlist (add/remove/list; verified symbol resolution).

    Implements: REQ-SI-FR-004
    """
    data_store = open_data_store()
    try:
        if action == "list":
            rows = data_store.watchlist.list()
            if not rows:
                typer.echo("watchlist is empty")
                return
            for row in rows:
                typer.echo(
                    f"{row['canonical_symbol']}  {row['official_name']}  {row['exchange']}  added {row['added_at']}"
                )
            return
        if action == "add":
            if not query:
                typer.secho("error: `watch add` requires a mention or name to resolve", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2)
            try:
                candidates = data_store.resolver.search(query)
            except ResolverUnavailable as exc:
                typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2) from exc
            if not candidates:
                typer.secho(
                    f"not found: no verified resolution for {query!r}; watchlist unchanged",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=1)
            for cand in candidates:
                data_store.record(cand)
            for i, cand in enumerate(candidates, start=1):
                typer.echo(f"{i}) {cand.canonical_symbol}  {cand.official_name}  exchange {cand.exchange}")
            if len(candidates) == 1:
                choice = 1
            else:
                raw = typer.prompt(f"select 1-{len(candidates)}")
                if not raw.isdigit() or not 1 <= int(raw) <= len(candidates):
                    typer.secho("error: invalid selection; cancelled", fg=typer.colors.RED, err=True)
                    raise typer.Exit(code=2)
                choice = int(raw)
            picked = candidates[choice - 1]
            if not typer.confirm(f"add {picked.canonical_symbol} ({picked.official_name})?"):
                typer.echo("cancelled; watchlist unchanged")
                return
            result = data_store.watchlist.add_verified(picked.canonical_symbol, user_confirmed=True, via="cli")
            typer.echo(
                f"added {result['canonical_symbol']} ({result['official_name']}); "
                f"backfill enqueued {result['backfill_enqueued']}"
            )
            return
        if action == "remove":
            if not query:
                typer.secho("error: `watch remove` requires a canonical symbol", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2)
            result = data_store.watchlist.remove(query)
            typer.echo(f"removed {result['canonical_symbol']} (status: {result['status']})")
            return
        typer.secho(f"error: unknown watch action {action!r} (list | add | remove)", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    except WatchlistError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    finally:
        data_store.close()


@app.command()
def info(symbol: str = typer.Argument(..., help="Canonical symbol, e.g. 0700.HK")) -> None:
    """Display the current basic information snapshot for a symbol.

    Implements: REQ-SI-FR-005
    """
    _stub("info", "REQ-SI-FR-005")


@app.command()
def analyze() -> None:
    """Enter an interactive analysis REPL session (interactive only).

    Implements: REQ-SI-FR-013
    """
    repl(SessionStore(), data_store=open_data_store())


@app.command()
def resume(
    session_id: str = typer.Argument(None, help="Session to resume (default: the most recent closed)."),
) -> None:
    """Resume a closed session and continue the conversation.

    Implements: REQ-SI-FR-023
    """
    try:
        resume_session(SessionStore(), session_id, data_store=open_data_store())
    except SessionError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None


@app.command()
def sessions(
    symbol: str = typer.Option(None, help="Filter by subject symbol, e.g. 0700.HK."),
    date: str = typer.Option(None, help="Filter by creation date prefix (YYYY-MM-DD)."),
) -> None:
    """List sessions from the sessions index.

    Implements: REQ-SI-FR-012
    """
    rows = SessionStore().list_sessions(symbol=symbol, date=date)
    if not rows:
        typer.echo("no sessions match the filter")
        return
    for row in rows:
        symbols = ",".join(row["subject_symbols"]) or "-"
        typer.echo(f"{row['session_id']}  {row['created']}  {row['status']}  {symbols}  {row['profile']}")


@app.command()
def show(
    session_id: str = typer.Argument(None, help="Session to render (default: the most recent)."),
) -> None:
    """Render a session for read-only review.

    Implements: REQ-SI-FR-022
    """
    store = SessionStore()
    target = session_id
    if target is None:
        rows = store.list_sessions()
        if not rows:
            typer.echo("no sessions available")
            return
        target = rows[-1]["session_id"]
    try:
        render_session(store, target, typer.echo)
    except SessionError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None


config_app = typer.Typer(help="Show or update provider/model/budget configuration.")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Display the resolved configuration (secrets masked).

    Implements: REQ-SI-FR-021, REQ-SI-SEC-001 (ADR-001)
    """
    resolved = resolve_config()
    key, source = resolve_api_key()
    path = config_path()
    suffix = "" if path.exists() else " (absent; defaults apply)"
    typer.echo(f"config file: {path}{suffix}")
    typer.echo(f"chat:       {resolved.chat_model} @ {resolved.chat_base_url or 'UNCONFIGURED'}")
    typer.echo(f"embedding:  {resolved.embedding_model} @ {resolved.embedding_base_url or 'UNCONFIGURED'}")
    typer.echo("budgets:    " + " ".join(f"{k}={v}" for k, v in sorted(resolved.budgets.items())))
    typer.echo(f"api key:    {mask_key(key)} ({source})")


@config_app.command("set")
def config_set(
    chat_base_url: str = typer.Option(None, help="Chat endpoint base URL (OpenAI-compatible)."),
    chat_model: str = typer.Option(None, help="Chat model identifier."),
    embedding_base_url: str = typer.Option(None, help="Embedding endpoint base URL."),
    embedding_model: str = typer.Option(None, help="Embedding model identifier."),
    budget_quick: int = typer.Option(None, help="Token budget override for the quick profile."),
    budget_standard: int = typer.Option(None, help="Token budget override for the standard profile."),
    budget_deep: int = typer.Option(None, help="Token budget override for the deep profile."),
    api_key: str = typer.Option(
        None,
        "--api-key",
        help="Write PROVIDER_API_KEY to .env (never stored in config.json).",
    ),
) -> None:
    """Update configuration values; secrets go to .env, never config.json.

    Implements: REQ-SI-FR-021, REQ-SI-SEC-001 (ADR-001)
    """
    if api_key is not None:
        path = write_env_api_key(api_key)
        typer.echo(f"api key written to {path} (masked: {mask_key(api_key)})")
    updates: dict[str, object] = {}
    if chat_base_url is not None:
        updates["chat_base_url"] = chat_base_url
    if chat_model is not None:
        updates["chat_model"] = chat_model
    if embedding_base_url is not None:
        updates["embedding_base_url"] = embedding_base_url
    if embedding_model is not None:
        updates["embedding_model"] = embedding_model
    if budget_quick is not None:
        updates["budget_quick"] = budget_quick
    if budget_standard is not None:
        updates["budget_standard"] = budget_standard
    if budget_deep is not None:
        updates["budget_deep"] = budget_deep
    if not updates:
        if api_key is None:
            typer.secho("nothing to set; see --help for options", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
        return
    save_config(updates)
    typer.echo(f"config updated: {sorted(updates)}")


@config_app.command("path")
def config_path_cmd() -> None:
    """Print the configuration file path.

    Implements: REQ-SI-FR-021 (ADR-001)
    """
    typer.echo(str(config_path()))


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
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the version and exit.",
        callback=_print_version,
        is_eager=True,
    ),
) -> None:
    """Local CLI financial analyst for HK + US equities."""
    if ctx.invoked_subcommand is None:
        repl(SessionStore(), data_store=open_data_store())


def main() -> None:
    """Console-script entry point.

    Implements: REQ-SI-FR-013
    """
    app()
