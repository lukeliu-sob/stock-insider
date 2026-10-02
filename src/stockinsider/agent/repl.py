"""REPL loop and slash-command dispatch (blueprint §7.2-§7.3).

Slash commands and CLI subcommands are two entries to one verb set; a
third verb set is forbidden. /tools lists the registry and directly
invokes deterministic read/compute tools. /show renders a session
read-only; /resume continues a closed session. Free-text turns run the
full agent pipeline (streaming, tool loop, guardrail) when the
provider is configured; otherwise they fail explicitly with
remediation guidance (INV-003: refuse to pretend success).

The loop talks to the user only through the ReplIO port (ADR-007):
PlainIO is the line REPL, byte for byte; the terminal UI (agent/tui)
is a second implementation over the same dispatch. SLASH_COMMANDS is
the one command table behind /help and the UI's completion.

Implements: REQ-SI-FR-013, REQ-SI-FR-022, REQ-SI-FR-023,
REQ-SI-FR-026, REQ-SI-INV-003 (ADR-001, ADR-005, ADR-007)
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from typing import Any

from stockinsider.agent.context import estimate_tokens
from stockinsider.agent.loop import TurnEngine, load_identity_prompt
from stockinsider.agent.profiles import Profile, apply_budget_overrides, envelope_for
from stockinsider.agent.providers import (
    API_KEY_ENV,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderError,
    resolve_api_key,
    resolve_config,
)
from stockinsider.agent.registry import (
    Registry,
    register_data_tools,
    register_market_tools,
    register_news_tools,
    register_sync_tools,
)
from stockinsider.agent.session import SessionError, SessionStore
from stockinsider.shared.tools import (
    EffectClass,
    SourceKind,
    ToolCall,
    ToolSpec,
)

PROMPT = "stockinsider> "  # non-TTY default; TTY gets the context prompt below

#: Strict confirmation-command shape (H3-6, TP-018): exactly 'confirm '
#: plus an 8-letter token. Anything else — including questions that
#: merely start with "confirm" — is a normal conversational turn and
#: reaches the model (the old prefix match swallowed them).
_CONFIRM_LINE = re.compile(r"^confirm\s+([a-z]{8})$")


class ReplIO(ABC):
    """The REPL's user-facing I/O port: one dispatch, two front-ends.

    The dispatch loop never writes to the terminal itself (ADR-007).
    progress and render default to echo; the remaining hooks are
    no-ops a front-end may override. Model text arrives only through
    render (final, changed text) and stream (post-check-gated replay).

    Implements: REQ-SI-FR-013, REQ-SI-FR-026 (ADR-007)
    """

    @abstractmethod
    def ask(self, prompt: str, *, main: bool) -> str:
        """Read one line; main=True is the command prompt (EOFError ends the loop).

        Implements: REQ-SI-FR-013, REQ-SI-FR-026 (ADR-007)
        """

    @abstractmethod
    def echo(self, line: str) -> None:
        """Show one line of command output or a notice.

        Implements: REQ-SI-FR-013, REQ-SI-FR-026 (ADR-007)
        """

    @abstractmethod
    def stream(self, piece: str) -> None:
        """Receive one post-check-gated replay delta of a verified answer.

        Implements: REQ-SI-FR-019, REQ-SI-INV-001 (ADR-007)
        """

    def progress(self, line: str) -> None:
        """Show one engine progress line (tool lines, footer, pending write).

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """
        self.echo(line)

    def render(self, text: str) -> None:
        """Show the engine's final text when it differs from the replay.

        Implements: REQ-SI-FR-008, REQ-SI-INV-001 (ADR-007)
        """
        self.echo(text)

    def status(self, snapshot: Callable[[], dict[str, Any]]) -> None:
        """Offer harness counters before the command prompt (lazy; plain ignores).

        Implements: REQ-SI-FR-026 (ADR-007)
        """

    def turn_started(self) -> None:
        """A conversational turn begins.

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """

    def turn_finished(self, outcome: Any | None) -> None:
        """A conversational turn ended (None: interrupted or failed).

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """

    def phase(self, name: str, detail: str) -> None:
        """The turn engine entered a phase (model, tool, verifying, revising).

        Implements: REQ-SI-FR-019, REQ-SI-FR-026 (ADR-007)
        """

    def pending_write(self, token: str, tool: str, arguments: Any) -> None:
        """The model proposed a write; its one-time token awaits the human.

        Implements: REQ-SI-INV-004, REQ-SI-FR-026 (ADR-005 Am3, ADR-007)
        """


class PlainIO(ReplIO):
    """The line REPL behind the port: input(), print(), raw stdout replay.

    Reproduces the pre-port behavior byte for byte (ADR-007; golden
    transcript test).

    Implements: REQ-SI-FR-013 (ADR-001, ADR-007)
    """

    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        echo: Callable[[str], None] = print,
    ) -> None:
        """Bind the line reader and writer (tests inject both)."""
        self._input_fn = input_fn
        self._echo = echo

    def ask(self, prompt: str, *, main: bool) -> str:
        """Read one line with the given prompt.

        Implements: REQ-SI-FR-013 (ADR-007)
        """
        return self._input_fn(prompt)

    def echo(self, line: str) -> None:
        """Write one line.

        Implements: REQ-SI-FR-013 (ADR-007)
        """
        self._echo(line)

    def stream(self, piece: str) -> None:
        """Write a replay delta straight to stdout, as the REPL always did.

        Implements: REQ-SI-FR-019 (ADR-007)
        """
        sys.stdout.write(piece)
        sys.stdout.flush()


@dataclass(frozen=True)
class SlashCommand:
    """One slash command: the single source for /help and UI completion.

    Implements: REQ-SI-FR-013, REQ-SI-FR-026 (ADR-007)
    """

    name: str
    usage: str
    group: str
    in_help: bool = True


#: Every dispatched slash command, in /help order (ADR-007: completion
#: reads this table too, so the UI can never grow a verb of its own).
#: Unimplemented commands (_NOT_IMPLEMENTED) stay out of it.
SLASH_COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("sessions", "/sessions [symbol] [page]", "session"),
    SlashCommand("show", "/show [id]", "session"),
    SlashCommand("resume", "/resume [id]", "session"),
    SlashCommand("report", "/report <canonical-symbol>", "analysis"),
    SlashCommand("watch", "/watch [list|add|remove ...]", "data"),
    SlashCommand("sync", "/sync [run|status]", "data"),
    SlashCommand("tools", "/tools [name [k=v ...]]", "tools"),
    SlashCommand("help", "/help", "", in_help=False),
    SlashCommand("exit", "/exit", ""),
)


def _context_prompt(data_store: Any) -> str:
    """Status prompt on a TTY; plain PROMPT otherwise (TP-015 P0-6).

    Tests and pipes see the unchanged plain prompt.

    Implements: REQ-SI-FR-013 (ADR-001)
    """
    if not sys.stdin.isatty():
        return PROMPT
    try:
        symbols = data_store.watchlist.list()
        remaining = data_store.sync_status()["budget"]["remaining"]
        return f"stockinsider [{len(symbols)} sym | {remaining} calls]> "
    except Exception:  # noqa: BLE001 — prompt must never crash the loop
        return PROMPT


#: Commands whose real behavior lands in later test plans; each fails
#: explicitly, naming its target requirement or design section.
_NOT_IMPLEMENTED: dict[str, str] = {
    "config": "REQ-SI-FR-021",
    "compact": "context compaction (blueprint §7.4)",
}


def _explicit_not_implemented(command: str, target: str, echo: Callable[[str], None]) -> None:
    echo(f"error: /{command} is not implemented yet (target: {target}); refusing to pretend success (INV-003).")


_ASCII = str.maketrans({chr(0x2014): "-", chr(0x2013): "-", chr(0xB7): "|", chr(0x2192): "->"})


def chrome(text: str) -> str:
    """ASCII-degrade REPL chrome strings (mirror of cli.render.chrome).

    The dependency direction forbids agent -> cli, so the mapping
    lives here too (TP-015 P0-1).

    Implements: REQ-SI-FR-013 (ADR-001)
    """
    return text.translate(_ASCII)


def _cmd_help(echo: Callable[[str], None]) -> None:
    """Grouped command listing from SLASH_COMMANDS; unimplemented commands stay hidden.

    Implements: REQ-SI-FR-013 (TP-015 P0-3; ADR-007)
    """
    groups: dict[str, list[str]] = {}
    for command in SLASH_COMMANDS:
        if command.in_help:
            groups.setdefault(command.group, []).append(command.usage)
    for group, usages in groups.items():
        prefix = f"{group:8} " if group else " " * 9
        echo(chrome(prefix + "  ".join(usages)))


PAGE_SIZE = 10


def _cmd_sessions(store: SessionStore, args: list[str], echo: Callable[[str], None]) -> None:
    """List sessions; /sessions [symbol] [page] (TP-015 P1-9).

    Implements: REQ-SI-FR-012 (ADR-001)
    """
    symbol = args[0] if args and not args[0].isdigit() else None
    page = 1
    for arg in args:
        if arg.isdigit():
            page = int(arg)
            break
    rows = store.list_sessions(symbol=symbol)
    if not rows:
        echo("no sessions match the filter")
        return
    total_pages = max(1, -(-len(rows) // PAGE_SIZE))
    page = max(1, min(page, total_pages))
    window = rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    if total_pages > 1:
        echo(f"(page {page}/{total_pages}; /sessions [symbol] [page] for more)")
    for row in window:
        symbols = ",".join(row["subject_symbols"]) or "-"
        echo(f"{row['session_id']}  {row['created']}  {row['status']}  {symbols}  {row['profile']}")


def build_registry(
    store: SessionStore,
    data_store: Any = None,
    embed_provider: "tuple[Any, str] | None" = None,
) -> Registry:
    """Register the default deterministic tool set (ADR-005).

    Handlers are closures over existing agent modules; the registry
    itself stays free of non-shared imports (dependency law). When a
    data store is provided (injected by the CLI composition layer),
    the data tools from agent/registry.register_data_tools are added —
    the repl never imports the data facade directly.

    Implements: REQ-SI-FR-013, REQ-SI-FR-004 (ADR-005)
    """
    registry = Registry()
    if data_store is not None:
        register_data_tools(registry, data_store)
        register_sync_tools(registry, data_store)
        register_market_tools(registry, data_store)
        register_news_tools(registry, data_store, embed_provider)
    registry.register(
        ToolSpec(
            name="budget.query",
            description="Context budget envelope for an analysis profile.",
            arguments_spec={"profile": "str"},
            result_spec="dict",
            effect_class=EffectClass.COMPUTE,
            source_kind=SourceKind.COMPUTED,
        ),
        _budget_query,
    )
    registry.register(
        ToolSpec(
            name="session.list",
            description="List sessions from the local authoritative store.",
            arguments_spec={},
            optional_spec={"symbol": "str", "date": "str"},
            result_spec="list",
            effect_class=EffectClass.READ,
            source_kind=SourceKind.API,
        ),
        lambda args: store.list_sessions(symbol=args.get("symbol"), date=args.get("date")),
    )
    registry.register(
        ToolSpec(
            name="context.estimate",
            description="Conservative token estimate for a text string.",
            arguments_spec={"text": "str"},
            result_spec="dict",
            effect_class=EffectClass.COMPUTE,
            source_kind=SourceKind.COMPUTED,
        ),
        lambda args: {"tokens": estimate_tokens(args["text"])},
    )
    return registry


def _budget_query(args: dict) -> dict:
    envelope = envelope_for(Profile(args["profile"]))
    return {"profile": envelope.profile.value, "max_session_tokens": envelope.max_session_tokens}


def _cmd_watch(
    registry: Registry,
    args: list[str],
    *,
    input_fn: Callable[[str], str],
    echo: Callable[[str], None],
) -> None:
    """Watchlist slash command, routed through registry tools (FR-004).

    The interactive confirmation happens here: only the human's yes to
    the [y/N] prompt opens the registry write gate (allow_write=True,
    INV-004). Write tools take no confirmation argument since H3
    (TP-017 PR-2); the calls send exactly the tool's arguments (TP-022).

    Implements: REQ-SI-FR-004, REQ-SI-INV-004 (ADR-005)
    """
    action = args[0] if args else "list"
    rest = args[1:]
    if action == "list":
        result = registry.execute(ToolCall(tool="watchlist.list", arguments={}, call_id="slash-watch"))
        if not result.ok:
            echo(f"error: {result.error}")
            return
        rows = result.result or []
        if not rows:
            echo("watchlist is empty")
            return
        for row in rows:
            echo(f"{row['canonical_symbol']}  {row['official_name']}  {row['exchange']}")
        return
    if action == "add":
        if not rest:
            echo("error: /watch add requires a mention or name to resolve")
            return
        search = registry.execute(
            ToolCall(tool="symbol.search", arguments={"query": " ".join(rest)}, call_id="slash-watch")
        )
        if not search.ok:
            echo(f"error: {search.error}")
            return
        candidates = search.result or []
        if not candidates:
            echo("not found: no verified resolution; watchlist unchanged")
            return
        # ADR-005 Am2 (TP-018): secondary-venue listings fold to a summary
        # line — a numbered row is a selectable candidate, and only
        # primary-exchange listings verify (HK/US scope).
        primary = [c for c in candidates if c["exchange"].upper() in ("HK", "US", "INDX")]
        folded = [c for c in candidates if c not in primary]
        if not primary:
            echo(
                "not found: no primary-exchange (HK/US) listing among "
                f"{len(candidates)} candidates; out-of-scope venues are not addable (INV-004)"
            )
            return
        for i, cand in enumerate(primary, start=1):
            echo(f"{i}) {cand['canonical_symbol']}  {cand['official_name']}  exchange {cand['exchange']}")
        if folded:
            venues = " ".join(sorted({c["exchange"] for c in folded}))
            echo(f"   (+{len(folded)} secondary-exchange listings folded: {venues})")
        candidates = primary
        if len(candidates) == 1:
            picked = candidates[0]
        else:
            choice = input_fn(f"select 1-{len(candidates)}: ").strip()
            if not choice.isdigit() or not 1 <= int(choice) <= len(candidates):
                echo("error: invalid selection; cancelled")
                return
            picked = candidates[int(choice) - 1]
        confirm = input_fn(f"add {picked['canonical_symbol']} ({picked['official_name']})? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            echo("cancelled; watchlist unchanged")
            return
        result = registry.execute(
            ToolCall(
                tool="watchlist.add",
                arguments={"canonical_symbol": picked["canonical_symbol"]},
                call_id="slash-watch",
            ),
            allow_write=True,
        )
        if result.ok:
            echo(f"added {picked['canonical_symbol']}; backfill enqueued")
        else:
            echo(f"error: {result.error}")
        return
    if action == "remove":
        if not rest:
            echo("error: /watch remove requires a canonical symbol")
            return
        confirm = input_fn(f"remove {rest[0]}? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            echo("cancelled; watchlist unchanged")
            return
        result = registry.execute(
            ToolCall(
                tool="watchlist.remove",
                arguments={"canonical_symbol": rest[0]},
                call_id="slash-watch",
            ),
            allow_write=True,
        )
        echo(f"removed {rest[0]}" if result.ok else f"error: {result.error}")
        return
    echo(f"error: unknown watch action {action!r} (list | add | remove)")


def _cmd_sync(registry: Registry, args: list[str], echo: Callable[[str], None]) -> None:
    """Sync slash command: run (default) or status, via registry tools.

    Typing /sync is the write confirmation (blueprint §9.1).

    Implements: REQ-SI-FR-001, REQ-SI-FR-013 (ADR-005)
    """
    action = args[0] if args else "run"
    if action == "status":
        result = registry.execute(ToolCall(tool="sync.status", arguments={}, call_id="slash-sync"))
        if not result.ok:
            echo(f"error: {result.error}")
            return
        status = result.result
        budget = status["budget"]
        echo(
            f"budget: {budget['used']}/{budget['cap']} calls used, {budget['remaining']} remaining; "
            f"active symbols: {status['active_symbols']}; pending gaps: {len(status['pending_gaps'])}"
        )
        for gap in status["pending_gaps"]:
            echo(f"  gap: {gap['canonical_symbol']} {gap['from_date']}..{gap['to_date']}")
        # TP-019 (INV-003): confirmed no-data ranges stay visible
        no_data = status.get("no_data_gaps", [])
        if no_data:
            echo(f"confirmed no-data ranges (vendor returned no bars after repeated attempts): {len(no_data)}")
            for gap in no_data:
                echo(f"  no-data: {gap['canonical_symbol']} {gap['from_date']}..{gap['to_date']}")
        return
    if action != "run":
        echo(f"error: unknown sync action {action!r} (run | status)")
        return
    result = registry.execute(
        ToolCall(tool="sync.run", arguments={}, call_id="slash-sync"),
        allow_write=True,
    )
    if not result.ok:
        echo(f"error: {result.error}")
        return
    report = result.result
    counts = report["counts"]
    calls = report["calls"]
    echo(
        f"sync {report['ran_at']}: {counts['ok']} ok, {counts['failed']} failed, "
        f"{counts['deferred']} deferred; calls {calls['used']}/{calls['cap']} "
        f"({calls['remaining']} remaining)"
    )
    for item in report["results"]:
        if item["status"] != "ok":
            echo(f"  {item['status']}: {item['symbol']} ({item['action']}) — {item['detail']}")


def _cmd_tools(registry: Registry, args: list[str], echo: Callable[[str], None]) -> None:
    if not args:
        for spec in registry.list_tools():
            echo(f"{spec.name} [{spec.effect_class.value}] {spec.description}")
        return
    name, *raw = args
    parsed: dict[str, str] = {}
    for token in raw:
        if "=" not in token:
            echo(f"error: malformed argument {token!r}; expected name=value")
            return
        key, _, value = token.partition("=")
        parsed[key] = value
    call = ToolCall(tool=name, arguments=parsed, call_id=f"repl-{uuid.uuid4().hex[:8]}")
    result = registry.execute(call)
    if result.ok:
        echo(
            f"ok: {result.result} (provenance: {result.provenance['source_kind']} @ {result.provenance['produced_at']})"
        )
    else:
        echo(f"error: {result.error}")


def repl(
    store: SessionStore,
    *,
    profile: Profile | str = Profile.standard,
    data_root: "str | None" = None,
    data_store: Any = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
    io: ReplIO | None = None,
) -> None:
    """Start a NEW session and run the interactive loop (legacy entry).

    Implements: REQ-SI-FR-013, REQ-SI-GOV-005 (ADR-001)
    """
    start_new_session(
        store,
        profile=profile,
        data_root=data_root,
        data_store=data_store,
        input_fn=input_fn,
        echo=echo,
        io=io,
    )


def start_new_session(
    store: SessionStore,
    *,
    profile: Profile | str = Profile.standard,
    data_root: "str | None" = None,
    data_store: Any = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
    io: ReplIO | None = None,
) -> None:
    """Create a session, stamp provenance, and run the interactive loop.

    The provider configuration is resolved once at session start and
    stamped into the session record (GOV-005); mid-session config
    changes do not affect an open session. Without an explicit io the
    plain front-end runs over input_fn/echo (ADR-007).

    Implements: REQ-SI-FR-013, REQ-SI-GOV-005, REQ-SI-FR-026 (ADR-001, ADR-007)
    """
    out = io if io is not None else PlainIO(input_fn, echo)
    config = resolve_config(data_root)
    apply_budget_overrides(config.budgets)
    prompt_version, _identity = load_identity_prompt()
    stamp = {
        "model_id": config.chat_model,
        "provider_config": config.chat_base_url or "unconfigured-endpoint",
        "prompt_version": prompt_version,
    }
    record = store.create(profile=profile, provenance=stamp)
    out.echo(
        f"session {record['session_id']} opened (profile: {record['profile']}); type /help for commands, /exit to leave"
    )
    record = _session_loop(store, record, data_root=data_root, data_store=data_store, io=out)
    store.close(record["session_id"])
    out.echo(f"session {record['session_id']} closed")
    out.echo(f"resume with: stockinsider resume {record['session_id']}")


def _most_recent(store: SessionStore, *, closed_only: bool) -> dict:
    rows = store.list_sessions()
    if closed_only:
        rows = [row for row in rows if row["status"] == "closed"]
    if not rows:
        state = "closed session to resume" if closed_only else "session"
        raise SessionError(f"no {state} available")
    return rows[-1]


def resume_session(
    store: SessionStore,
    session_id: str | None = None,
    *,
    profile: Profile | str | None = None,
    data_root: "str | None" = None,
    data_store: Any = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
    io: ReplIO | None = None,
) -> None:
    """Resume a closed session (default: the most recent) and continue the loop.

    Prior turns are never rewritten: new turns append to the same
    session.jsonl (FR-023). Aborted sessions are terminal (H4 residual,
    TP-018): resume() refuses them — the abort verdict survives
    process restarts. The profile lock is validated on resume.

    Implements: REQ-SI-FR-023, REQ-SI-FR-026 (ADR-001, ADR-007)
    """
    out = io if io is not None else PlainIO(input_fn, echo)
    target = session_id or _most_recent(store, closed_only=True)["session_id"]
    record = store.resume(target, profile=profile)
    restored = len(store.read_events(record["session_id"]))
    out.echo(
        f"session {record['session_id']} resumed (profile: {record['profile']}; "
        f"{restored} events restored); type /help for commands, /exit to leave"
    )
    record = _session_loop(store, record, data_root=data_root, data_store=data_store, io=out)
    store.close(record["session_id"])
    out.echo(f"session {record['session_id']} closed")
    out.echo(f"resume with: stockinsider resume {record['session_id']}")


def _close_after_failure(store: SessionStore, record: dict) -> None:
    """Close the bound session when the loop dies; the original error still propagates.

    A crashed front-end used to leave the session "active" (ADR-007
    §1.9). A failing close must not mask the error that ended the loop.
    """
    try:
        store.close(record["session_id"])
    except Exception:  # noqa: BLE001 - the exception being propagated is the one to report
        pass


def _status_snapshot(store: SessionStore, record: dict, data_store: Any) -> dict[str, Any]:
    """Harness counters for a front-end status line (ADR-007 §1.6c).

    Session id, profile, model, token usage against the profile
    envelope, the last post-check verdict, watchlist size and the call
    budget. Never market data. A counter that cannot be read stays None
    (shown as unknown, never as a default value - INV-003).
    """
    snapshot: dict[str, Any] = {
        "session_id": record.get("session_id"),
        "profile": record.get("profile"),
        "model": (record.get("provenance") or {}).get("model_id"),
        "budget_tokens": None,
        "session_tokens": None,
        "last_verdict": None,
        "watchlist": None,
        "calls_remaining": None,
    }
    try:
        snapshot["budget_tokens"] = envelope_for(record["profile"]).max_session_tokens
    except (KeyError, ValueError):
        pass
    try:
        used = 0
        verdict = "none"
        for event in store.read_events(record["session_id"]):
            if event.get("event") == "assistant-message":
                usage = event.get("usage") or {}
                used += int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0))
                verdict = {"ok": "pass", "flagged": "flagged"}.get(str(event.get("post_check")), "failed")
        snapshot["session_tokens"] = used
        snapshot["last_verdict"] = verdict
    except (SessionError, OSError, ValueError, TypeError):
        pass
    if data_store is not None:
        try:
            snapshot["watchlist"] = len(data_store.watchlist.list())
        except Exception:  # noqa: BLE001 - a status line must never crash the loop
            pass
        try:
            snapshot["calls_remaining"] = data_store.sync_status()["budget"]["remaining"]
        except Exception:  # noqa: BLE001 - a status line must never crash the loop
            pass
    return snapshot


def _session_loop(
    store: SessionStore,
    record: dict,
    *,
    data_root: "str | None" = None,
    data_store: Any = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
    io: ReplIO | None = None,
) -> dict:
    """Run the interactive loop; returns the FINAL bound record.

    /resume may switch the binding mid-loop; the returned record is
    the session the entry must close. If the loop dies on an exception,
    the session bound at that moment is closed before the exception
    propagates (ADR-007 §1.9).

    Implements: REQ-SI-FR-013, REQ-SI-FR-023, REQ-SI-FR-026 (ADR-001, ADR-007)
    """
    out = io if io is not None else PlainIO(input_fn, echo)
    binding = [record]  # the session bound right now; /resume rebinds it
    try:
        return _dispatch_loop(store, binding, data_root=data_root, data_store=data_store, out=out)
    except BaseException:
        _close_after_failure(store, binding[0])
        raise


def _dispatch_loop(
    store: SessionStore,
    binding: list[dict],
    *,
    data_root: "str | None",
    data_store: Any,
    out: ReplIO,
) -> dict:
    """The slash-command and conversational dispatch behind _session_loop."""
    record = binding[0]
    config = resolve_config(data_root)
    apply_budget_overrides(config.budgets)
    embed_provider = _build_embed_provider(config)
    registry = build_registry(store, data_store, embed_provider)
    engine = _build_engine(store, registry, config)

    def _ask_sub(prompt: str) -> str:
        return out.ask(prompt, main=False)

    while True:
        out.status(partial(_status_snapshot, store, record, data_store))
        try:
            line = out.ask(_context_prompt(data_store), main=True).strip()
        except EOFError:
            break
        if not line:
            continue
        if line == "/exit":
            break
        confirm_match = _CONFIRM_LINE.match(line)
        if confirm_match and engine is not None:
            # H3 (TP-018): human confirmation for a proposed write. The
            # pending write and its token were rendered by the harness when
            # the model proposed the call (non-relay principle, ADR-005
            # Am3) — this path only ever consumes what the user read.
            token = confirm_match.group(1)
            pending = engine.confirmations.consume(token)
            if pending is None:
                out.echo("unknown or already-used token; nothing executed (INV-004)")
                continue
            confirmed_result = engine.registry.execute(
                ToolCall(
                    tool=pending.tool,
                    arguments=pending.arguments,
                    call_id=f"confirm-{token}",
                ),
                allow_write=True,  # the consumed token IS the human's consent
            )
            bound = f"{pending.tool} {json.dumps(pending.arguments, sort_keys=True)}"
            outcome_note = "ok" if confirmed_result.ok else f"failed: {confirmed_result.error}"
            # H3-4 (TP-018): the confirmation outcome enters the model's
            # history — user/assistant events are exactly what
            # _history_messages reads — so a later /report can no longer
            # truthfully claim a confirmed add never happened. The
            # tool-call/tool-result pair keeps the authoritative record.
            store.append_event(
                record["session_id"],
                {
                    "event": "tool-call",
                    "tool": pending.tool,
                    "arguments": pending.arguments,
                    "turn": None,
                },
            )
            store.append_event(
                record["session_id"],
                {
                    "event": "tool-result",
                    "tool": pending.tool,
                    "ok": confirmed_result.ok,
                    "result": confirmed_result.result,
                    "provenance": confirmed_result.provenance,
                    "turn": None,
                },
            )
            store.append_event(
                record["session_id"],
                {
                    "event": "user-message",
                    "text": f"[harness] confirmed write executed: {bound} -> {outcome_note}",
                    "turn": None,
                },
            )
            if confirmed_result.ok:
                out.echo(f"confirmed: {bound} executed (single-use token consumed)")
            else:
                out.echo(f"confirmed but failed: {bound} -> {confirmed_result.error}")
            continue
        if line.startswith("/"):
            parts = line[1:].split()
            if not parts:  # H5: bare "/" never crashes the loop
                out.echo("unknown command: '/' (type /help for the command list)")
                continue
            name, *args = parts
            if name == "help":
                _cmd_help(out.echo)
            elif name == "sessions":
                _cmd_sessions(store, args, out.echo)
            elif name == "tools":
                _cmd_tools(registry, args, out.echo)
            elif name == "show":
                target = args[0] if args else record["session_id"]
                try:
                    render_session(store, target, out.echo)
                except SessionError as exc:
                    out.echo(f"error: {exc}")
            elif name == "report":
                if not args:
                    out.echo("usage: /report <canonical-symbol>")
                    continue
                if engine is None:
                    out.echo(
                        "report requires a configured provider "
                        f"(set {API_KEY_ENV} and the chat base_url); nothing generated"
                    )
                    continue
                try:
                    _run_report_turn(engine, store, record, args[0], out.echo, io=out)
                except SessionError as exc:
                    out.echo(f"error: {exc}")
            elif name == "watch":
                _cmd_watch(
                    registry,
                    args,
                    input_fn=_ask_sub,
                    echo=out.echo,
                )
            elif name == "sync":
                _cmd_sync(registry, args, out.echo)
            elif name == "resume":
                try:
                    if args:
                        resolved = args[0]
                    else:
                        closed = [row for row in store.list_sessions() if row["status"] == "closed"]
                        if not closed:
                            _most_recent(store, closed_only=True)  # raises the canonical error
                            continue
                        closed.reverse()  # most recent first (index order is oldest-first)
                        out.echo("closed sessions (most recent first):")
                        for i, row in enumerate(closed, start=1):
                            symbols = ",".join(row["subject_symbols"]) or "-"
                            out.echo(f"  {i}) {row['session_id']}  {row['created']}  {row['profile']}  {symbols}")
                        choice = _ask_sub(f"select 1-{len(closed)} (enter=1, q=cancel): ").strip()
                        if choice.lower() == "q":
                            out.echo("resume cancelled")
                            continue
                        if choice == "":
                            choice = "1"
                        if not choice.isdigit() or not 1 <= int(choice) <= len(closed):
                            out.echo(f"error: invalid selection {choice!r}; resume cancelled")
                            continue
                        resolved = closed[int(choice) - 1]["session_id"]
                    if resolved == record["session_id"]:
                        out.echo("error: already in this session; /resume switches to a different closed session")
                        continue
                    # Fourth-audit fix (TP-018b): peek at the target BEFORE
                    # closing the current session. Resuming an aborted
                    # session used to close the live one first, then raise,
                    # leaving the loop appending events to a closed record.
                    target_row = next(
                        (row for row in store.list_sessions() if row["session_id"] == resolved), None
                    )
                    if target_row is not None and target_row.get("status") == "aborted":
                        out.echo(
                            f"error: session {resolved} was aborted by the guardrail; "
                            "aborted sessions are terminal — start a new session (INV-003)"
                        )
                        continue
                    store.close(record["session_id"])
                    out.echo(f"session {record['session_id']} closed (switching)")
                    record = store.resume(resolved)
                    binding[0] = record
                    engine = _build_engine(store, registry, config)
                    out.echo(
                        f"session {record['session_id']} resumed "
                        f"(profile: {record['profile']}; aborted sessions are refused)"
                    )
                except SessionError as exc:
                    out.echo(f"error: {exc}")
            elif name in _NOT_IMPLEMENTED:
                _explicit_not_implemented(name, _NOT_IMPLEMENTED[name], out.echo)
            else:
                out.echo(f"error: unknown command /{name}; /help lists available commands")
        else:
            if engine is None:
                out.echo(
                    "error: provider unconfigured — run `stockinsider config set "
                    "--chat-base-url ...` and `--api-key` (or set PROVIDER_BASE_URL / "
                    f"{API_KEY_ENV}); slash commands remain available"
                )
            else:
                outcome = _run_conversational_turn(engine, record, line, out)
                if outcome is not None and getattr(outcome, "aborted", None):
                    # H4: the abort threshold is sticky — leave the loop
                    # instead of accepting further turns on an aborted session.
                    out.echo("closing the session (abort threshold reached)")
                    break
    return record


def _build_embed_provider(config: ProviderConfig) -> "tuple[Any, str] | None":
    """The (provider, model_id) pair for news.search, when configured.

    Implements: REQ-SI-FR-007 (ADR-001)
    """
    if not config.embedding_base_url:
        return None
    key, _source = resolve_api_key()
    if key is None:
        return None
    provider = OpenAICompatibleProvider(config, api_key=key)
    return provider, config.embedding_model


def _build_engine(store: SessionStore, registry: Registry, config: ProviderConfig) -> TurnEngine | None:
    """Construct the turn engine when the provider is fully configured.

    Implements: REQ-SI-FR-008 (ADR-001)
    """
    key, _source = resolve_api_key()
    if not config.chat_base_url or key is None:
        return None
    provider = OpenAICompatibleProvider(config, api_key=key)
    return TurnEngine(store, registry, provider)


def _run_report_turn(
    engine: TurnEngine,
    store: SessionStore,
    record: dict,
    symbol: str,
    echo: Callable[[str], None],
    *,
    io: ReplIO | None = None,
) -> "Any | None":
    """Compose and run the analysis-report turn; persist on pass (FR-008).

    The report instruction gathers deterministic facts first; the
    engine's post-check runs as always. A passing response is stored
    as a never-overwritten artifact with the session's provenance
    stamp; a failing response degrades and NOTHING is stored. Without
    an explicit io the plain front-end writes through echo (ADR-007).

    Implements: REQ-SI-FR-008, REQ-SI-INV-001 (ADR-001, ADR-007)
    """
    out = io if io is not None else PlainIO(echo=echo)
    instruction = (
        f"Produce an analysis report for {symbol}. Gather the deterministic facts "
        "first via tools: market.quote, market.indicators, and fundamentals.summary "
        "(plus news.search when it is available). Cite every numeric exactly as "
        "returned by the tools, with its data date or window; keep interpretations "
        "explicitly labeled as hypotheses (INV-002). Output only the report itself: "
        "do not acknowledge earlier turns or harness notes in it (TP-019 - the "
        "stored artifact is the report)."
    )
    outcome = _run_conversational_turn(engine, record, instruction, out)
    if outcome is None:
        return None
    if getattr(outcome, "quarantined", False) or getattr(outcome, "aborted", None):
        out.echo("report not stored: the response failed the post-check (FR-008)")
        return outcome
    if getattr(outcome, "refused", False):
        # TP-019: an INV-002 refusal summary is not a report
        out.echo("report not stored: the response was refused by the epistemic filter (INV-002)")
        return outcome
    # TP-019: the artifact is the report body - conversational prelude
    # emitted before the tool calls ("Understood, the watchlist...")
    # stays in the session log, not in the stored report
    displayed = getattr(outcome, "body", "") or getattr(outcome, "displayed", "")
    if not displayed.strip():
        out.echo("report not stored: empty response")
        return outcome
    safe_symbol = symbol.replace(".", "_").replace(":", "_")
    artifacts = store._require(record["session_id"]) / "artifacts"  # noqa: SLF001
    existing = len(list(artifacts.glob(f"report-{safe_symbol}-*.md"))) if artifacts.exists() else 0
    stamp = record.get("provenance", {})
    # ADR-008: a report with unverified numbers is stored with its markers
    # and says so in the header; only a fully verified one claims the pass.
    unverified = list(getattr(outcome, "unverified", None) or [])
    if unverified:
        verdict_line = (
            f"- unverified numbers: {len(unverified)} (marked [?]; not verified by the INV-001 post-check)\n"
        )
    else:
        verdict_line = "- stored: passed the INV-001 post-check before persistence (FR-008)\n"
    header = (
        f"# Analysis report — {symbol}\n\n"
        f"- session: {record['session_id']}\n"
        f"- model: {stamp.get('model_id', 'unknown')}\n"
        f"- prompt: {stamp.get('prompt_version', 'unknown')}\n"
        f"{verdict_line}\n---\n\n"
    )
    path = store.artifact(
        record["session_id"],
        f"report-{safe_symbol}-{existing + 1:03d}.md",
        header + displayed + "\n",
    )
    if unverified:
        noun = "number" if len(unverified) == 1 else "numbers"
        out.echo(f"report stored: {path.name} ({len(unverified)} unverified {noun} marked [?])")
    else:
        out.echo(f"report stored: {path.name}")
    return outcome


def _run_conversational_turn(engine: TurnEngine, record: dict, line: str, out: ReplIO) -> "Any | None":
    """Run one free-text turn with streaming render and explicit failures.

    Returns the engine's TurnOutcome (or None when interrupted). The
    front-end hears turn start and finish on every path, so an activity
    indicator can never outlive its turn (ADR-007).

    Implements: REQ-SI-FR-008, REQ-SI-FR-019, REQ-SI-FR-026 (ADR-001, ADR-007)
    """
    out.turn_started()
    try:
        outcome = engine.run_turn(
            record["session_id"],
            line,
            profile=record["profile"],
            render=out.render,
            progress=out.progress,
            stream_sink=out.stream,
            on_phase=out.phase,
            on_pending_write=out.pending_write,
        )
    except KeyboardInterrupt:
        out.turn_finished(None)
        out.echo("\nturn interrupted")
        return None
    except ProviderError as exc:
        out.turn_finished(None)
        out.echo(f"error: {exc}")
        return None
    except RuntimeError as exc:
        # Defense in depth (ADR-004 Am2, TP-018): an egress policy
        # rejection (or any guard-adjacent RuntimeError) degrades to an
        # explicit error line — a policy rejection must never crash the
        # REPL into a stuck "active" session.
        out.turn_finished(None)
        out.echo(f"error: {type(exc).__name__}: {exc}")
        return None
    except BaseException:
        out.turn_finished(None)
        raise
    out.turn_finished(outcome)
    return outcome


def render_session(store: SessionStore, session_id: str, echo: Callable[[str], None]) -> None:
    """Render one session read-only from its authoritative event log (FR-022).

    Tool calls are enumerated in exact session.jsonl order with their
    arguments; quarantined originals are shown flagged; snapshot
    values and artifacts are listed. Raises SessionError for unknown
    sessions.

    Implements: REQ-SI-FR-022 (ADR-001)
    """
    events = store.read_events(session_id)
    header = dict(events[0].get("record", {})) if events else {}
    current = next((row for row in store.list_sessions() if row["session_id"] == session_id), None)
    if current:
        header.update({k: current[k] for k in ("profile", "status") if k in current})
    provenance = header.get("provenance", {})
    echo(f"session {session_id} ({header.get('profile', '?')} · {header.get('status', '?')})")
    echo(
        f"stamps: model={provenance.get('model_id', '?')} · "
        f"prompt={provenance.get('prompt_version', '?')} · "
        f"provider={provenance.get('provider_config', '?')}"
    )
    turn = None
    for event in events[1:]:
        kind = event.get("event")
        event_turn = event.get("turn")
        if event_turn and event_turn != turn:
            turn = event_turn
            echo(f"── {turn}")
        if kind == "user-message":
            echo(f"  user>      {event.get('text', '')}")
        elif kind == "tool-call":
            echo(f"  tool-call  {event.get('tool', '?')} {json.dumps(event.get('arguments', {}))}")
        elif kind == "tool-result":
            ok = event.get("ok")
            source = event.get("provenance", {}).get("source_kind", "?")
            preview = json.dumps(event.get("result")) if ok else str(event.get("result"))
            echo(f"  tool-result {'ok' if ok else 'failed'} {preview[:80]} ({source if ok else 'error'})")
        elif kind == "assistant-message":
            usage = event.get("usage", {})
            tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            echo(
                f"  assistant  {event.get('text', '')} [post-check: {event.get('post_check', '?')} · tokens: {tokens}]"
            )
        elif kind == "error":
            original = event.get("original")
            if event.get("kind") == "epistemic":
                # TP-019: INV-002 record - what was removed and what replaced it
                echo(
                    f"  error      epistemic -> {event.get('outcome', '?')} "
                    f"(violating original: {original!r}; violations: {event.get('violations', [])!r})"
                )
            elif original:
                echo(f"  error      {event.get('kind', '?')} (quarantined original: {original!r})")
            else:
                echo(f"  error      {event.get('kind', '?')} turn={event.get('turn', '?')}")
    session_dir = store.root / session_id
    context_dir = session_dir / "context"
    if context_dir.is_dir():
        for path in sorted(context_dir.glob("turn-*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            preview = json.dumps(payload.get("values", {}))
            echo(f"snapshot    {path.stem}: {preview[:100]}")
    artifacts_dir = session_dir / "artifacts"
    names = sorted(p.name for p in artifacts_dir.iterdir()) if artifacts_dir.is_dir() else []
    echo(f"artifacts: {', '.join(names) if names else '(none)'}")
