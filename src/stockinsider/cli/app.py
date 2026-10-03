"""Typer application: FR-013 subcommand surface.

Six subcommands remain explicit-failure stubs (English error naming
the target requirement, non-zero exit — INV-003 semantics); `sessions`
lists from the sessions index (FR-012), `analyze` and bare invocation
enter the REPL (FR-013), and `config` shows/updates the layered
provider configuration (FR-021, SEC-001). `--ui tui` selects the opt-in
terminal UI for the interactive entries (FR-026, ADR-007); plain stays
the default.

Implements: REQ-SI-FR-013, REQ-SI-FR-026, REQ-SI-INV-003 (ADR-001, ADR-007)
"""

from enum import Enum
from typing import NoReturn, Optional

import typer

from stockinsider import __version__
from stockinsider.agent.providers import (
    OpenAICompatibleProvider,
    config_path,
    mask_key,
    resolve_api_key,
    resolve_config,
    save_config,
    write_env_api_key,
)
from time import monotonic

from stockinsider.cli.render import (
    chrome,
    day_change_styled,
    info_lines_chromed,
    init_output,
    news_track_lines,
    render_error,
    sync_notable_lines,
    sync_summary_line,
    sync_verbose_lines,
)
from stockinsider.agent.repl import render_session, repl, resume_session
from stockinsider.agent.session import SessionError, SessionStore
from stockinsider.data.ingest.market import MarketKeyMissing
from stockinsider.data.store.resolver import (
    SYMBOL_SHAPE,
    fold_secondaries,
    order_candidates,
)
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


class UIMode(str, Enum):
    """Interactive front-end: the plain REPL (default) or the terminal UI.

    Implements: REQ-SI-FR-026 (ADR-007)
    """

    plain = "plain"
    tui = "tui"


_UI_ENV = "STOCKINSIDER_UI"
_UI_HELP = "Interactive front-end: plain (default) or tui (inline terminal UI; needs an interactive terminal)."


def _ui_for(ctx: typer.Context, ui: Optional[UIMode]) -> UIMode:
    """A subcommand's own --ui wins; otherwise the root option's value applies."""
    if ui is not None:
        return ui
    inherited = (ctx.obj or {}).get("ui") if isinstance(ctx.obj, dict) else None
    return inherited if isinstance(inherited, UIMode) else UIMode.plain


def _interactive(ui: UIMode, *, resume: bool = False, session_id: Optional[str] = None) -> None:
    """Run the REPL under the selected front-end (ADR-007).

    The terminal UI checks its terminal, console and dependency before
    any session opens. An unusable terminal falls back to the plain
    REPL with an explicit notice; a missing dependency is an explicit
    error (INV-003).
    """
    store = SessionStore()
    data_store = open_data_store()
    if ui is UIMode.tui:
        from stockinsider.agent.tui import TuiDependencyMissing, TuiUnavailable, run_tui

        try:
            run_tui(store, data_store=data_store, resume=resume, session_id=session_id)
            return
        except TuiDependencyMissing as exc:
            typer.secho(render_error(str(exc)), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        except TuiUnavailable as exc:
            typer.echo(f"note: terminal UI unavailable ({exc}); using the plain REPL", err=True)
    if resume:
        resume_session(store, session_id, data_store=data_store)
    else:
        repl(store, data_store=data_store)


def _stub(command: str, req: str) -> NoReturn:
    """Emit the explicit not-implemented failure and exit non-zero."""
    typer.secho(_STUB_NOTE.format(command=command, req=req), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2)


@app.command()
def sync(
    verbose: bool = typer.Option(False, "--verbose", help="Show every plan item, not just failures."),
) -> None:
    """Ingest daily EOD market data under the call budget (idempotent).

    Progress lines stream during the run; the tail is a compact
    summary with failures always visible (TP-015 P0).

    Implements: REQ-SI-FR-001
    """
    started = monotonic()

    def _emit(line: str) -> None:
        print(chrome(line), flush=True)

    data_store = open_data_store()
    try:
        report = data_store.run_sync(progress=_emit)
    finally:
        data_store.close()
    typer.echo(sync_summary_line(report))
    if verbose:
        for line in sync_verbose_lines(report):
            typer.echo(line)
    else:
        for line in sync_notable_lines(report):
            typer.echo(line)
    for line in news_track_lines(report):
        typer.echo(line)
    typer.echo(f"sync total wall time {monotonic() - started:.1f}s")
    if report["counts"]["failed"]:
        raise typer.Exit(code=1)


@app.command()
def embed() -> None:
    """Embed pending news rows into the retrieval index (idempotent).

    Implements: REQ-SI-FR-007
    """
    from stockinsider.data.ingest.embed import run_embed

    config = resolve_config()
    key, _source = resolve_api_key()
    if not config.embedding_base_url or key is None:
        typer.echo("embedding provider not configured (embedding base_url + api key required); nothing done")
        raise typer.Exit(code=1)
    provider = OpenAICompatibleProvider(config, api_key=key)
    data_store = open_data_store()
    try:
        report = run_embed(data_store.conn, provider.embed, config.embedding_model)
    finally:
        data_store.close()
    typer.echo(
        f"embed {report['ran_at']}: model {report['model_id']}, "
        f"{report['embedded']} embedded ({report['pending_before']} pending before)"
    )
    for batch in report["failed_batches"]:
        shown = batch["news_ids"][:3]
        more = f"... +{len(batch['news_ids']) - 3}" if len(batch["news_ids"]) > 3 else ""
        typer.echo(f"failed  {batch['error']} (news_ids {shown}{more})")
    if report["failed_batches"]:
        raise typer.Exit(code=1)


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
                # DE-11 (TP-026 plan): a row whose resolution migration v6
                # demoted (secondary-venue, ADR-005 Am2) stays active and
                # keeps syncing - visible here, not silently trusted.
                flag = "  [unverified resolution]" if not row["verified"] else ""
                typer.echo(
                    f"{row['canonical_symbol']}  {row['official_name']}  {row['exchange']}  "
                    f"added {row['added_at']}{flag}"
                )
            return
        if action == "add":
            if not query:
                typer.secho(
                    render_error("`watch add` requires a mention or name to resolve"),
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=2)
            try:
                if SYMBOL_SHAPE.match(query.strip()):
                    # Direct verification path (BD-017): vendor search does
                    # not index HK listings; one budgeted EOD fetch proves
                    # existence. INV-004 confirmation unchanged below.
                    verified = data_store.verify_symbol(query.strip())
                    candidates = [verified] if verified is not None else []
                    if not candidates:
                        typer.secho(
                            f"not found: {query.strip()} returned no data via direct verification; watchlist unchanged",
                            fg=typer.colors.RED,
                            err=True,
                        )
                        raise typer.Exit(code=1)
                else:
                    candidates = order_candidates(data_store.resolver.search(query), query)
            except (ResolverUnavailable, MarketKeyMissing) as exc:
                typer.secho(render_error(str(exc)), fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2) from exc
            if not candidates:
                typer.secho(
                    f"not found: no verified resolution for {query!r}; watchlist unchanged",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=1)
            visible, folded_count, folded_exchanges = fold_secondaries(candidates)
            for cand in candidates:
                data_store.record(cand)
            for i, cand in enumerate(visible, start=1):
                badge = f"  [{cand.asset_type}]" if cand.asset_type not in ("stock", "unverified") else ""
                typer.echo(f"{i}) {cand.canonical_symbol}  {cand.official_name}  exchange {cand.exchange}{badge}")
            if folded_count:
                typer.echo(
                    f"   (+{folded_count} secondary-exchange listings folded: "
                    f"{' '.join(sorted(set(folded_exchanges)))}; use a full "
                    "symbol like AAPL.MU if you specifically want one)"
                )
            candidates = visible
            if len(candidates) == 1:
                choice = 1
            else:
                raw = typer.prompt(f"select 1-{len(candidates)}")
                if not raw.isdigit() or not 1 <= int(raw) <= len(candidates):
                    typer.secho(render_error("invalid selection; cancelled"), fg=typer.colors.RED, err=True)
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
                typer.secho(render_error("`watch remove` requires a canonical symbol"), fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2)
            result = data_store.watchlist.remove(query)
            typer.echo(f"removed {result['canonical_symbol']} (status: {result['status']})")
            return
        typer.secho(
            render_error(f"unknown watch action {action!r} (list | add | remove)"),
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    except WatchlistError as exc:
        typer.secho(render_error(str(exc)), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    finally:
        data_store.close()


@app.command()
def info(symbol: str = typer.Argument(..., help="Canonical symbol, e.g. 0700.HK")) -> None:
    """Display the current basic information snapshot for a symbol.

    Implements: REQ-SI-FR-005
    """
    data_store = open_data_store()
    try:
        try:
            lines = data_store.info_lines(symbol)
        except Exception as exc:  # noqa: BLE001 — explicit not-found path
            typer.secho(render_error(str(exc)), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        for line in info_lines_chromed(lines):
            typer.echo(day_change_styled(symbol, line))
    finally:
        data_store.close()


@app.command()
def analyze(
    ctx: typer.Context,
    ui: Optional[UIMode] = typer.Option(None, "--ui", envvar=_UI_ENV, case_sensitive=False, help=_UI_HELP),
) -> None:
    """Enter an interactive analysis REPL session (interactive only).

    Implements: REQ-SI-FR-013, REQ-SI-FR-026
    """
    _interactive(_ui_for(ctx, ui))


@app.command()
def resume(
    ctx: typer.Context,
    session_id: str = typer.Argument(None, help="Session to resume (default: the most recent closed)."),
    ui: Optional[UIMode] = typer.Option(None, "--ui", envvar=_UI_ENV, case_sensitive=False, help=_UI_HELP),
) -> None:
    """Resume a closed session and continue the conversation.

    Implements: REQ-SI-FR-023, REQ-SI-FR-026
    """
    try:
        _interactive(_ui_for(ctx, ui), resume=True, session_id=session_id)
    except SessionError as exc:
        typer.secho(render_error(str(exc)), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None


@app.command()
def sessions(
    symbol: str = typer.Option(None, help="Filter by subject symbol, e.g. 0700.HK."),
    date: str = typer.Option(None, help="Filter by creation date prefix (YYYY-MM-DD)."),
    status: str = typer.Option(None, help="Filter by status: active | closed."),
    limit: int = typer.Option(None, help="Show at most N sessions (hint on truncation)."),
) -> None:
    """List sessions from the sessions index.

    Implements: REQ-SI-FR-012 (TP-015 P1-9)
    """
    rows = SessionStore().list_sessions(symbol=symbol, date=date)
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    if not rows:
        typer.echo("no sessions match the filter")
        return
    total = len(rows)
    if limit is not None and limit >= 0 and total > limit:
        rows = rows[-limit:]
        typer.echo(f"(showing the {limit} most recent of {total}; raise --limit for more)")
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
        typer.secho(render_error(str(exc)), fg=typer.colors.RED, err=True)
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
    # ADR-004 Am2 (TP-018): endpoint URLs validate at WRITE time, not at
    # first question - a bad host is rejected here, naming the extension
    # path, instead of crashing a live session later (new-4).
    from stockinsider.shared.egress import EgressViolationError, provider_egress_allowed, validate_egress_url

    for field in ("chat_base_url", "embedding_base_url"):
        url = updates.get(field)
        if not isinstance(url, str):
            continue
        try:
            validate_egress_url(url, extra_allowed=provider_egress_allowed())
        except EgressViolationError as exc:
            typer.secho(
                f"error: {exc}; to allow this host, add it to EGRESS_EXTRA_HOSTS "
                "in your environment file (explicit owner decision, SEC-003)",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2) from exc
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
    ui: UIMode = typer.Option(UIMode.plain, "--ui", envvar=_UI_ENV, case_sensitive=False, help=_UI_HELP),
) -> None:
    """Local CLI financial analyst for HK + US equities."""
    init_output()
    ctx.obj = {"ui": ui}
    if ctx.invoked_subcommand is None:
        _interactive(ui)


def main() -> None:
    """Console-script entry point.

    Implements: REQ-SI-FR-013
    """
    app()
