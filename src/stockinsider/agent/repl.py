"""REPL loop and slash-command dispatch (blueprint §7.2-§7.3).

Slash commands and CLI subcommands are two entries to one verb set; a
third verb set is forbidden. /tools lists the registry and directly
invokes deterministic read/compute tools. /show renders a session
read-only; /resume continues a closed session. Free-text turns run the
full agent pipeline (streaming, tool loop, guardrail) when the
provider is configured; otherwise they fail explicitly with
remediation guidance (INV-003: refuse to pretend success).

Implements: REQ-SI-FR-013, REQ-SI-FR-022, REQ-SI-FR-023,
REQ-SI-INV-003 (ADR-001, ADR-005)
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable

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
    register_sync_tools,
)
from stockinsider.agent.session import SessionError, SessionStore
from stockinsider.shared.tools import (
    EffectClass,
    SourceKind,
    ToolCall,
    ToolSpec,
)

PROMPT = "stockinsider> "

#: Commands whose real behavior lands in later test plans; each fails
#: explicitly, naming its target requirement or design section.
_NOT_IMPLEMENTED: dict[str, str] = {
    "config": "REQ-SI-FR-021",
    "compact": "context compaction (blueprint §7.4)",
}


def _explicit_not_implemented(command: str, target: str, echo: Callable[[str], None]) -> None:
    echo(f"error: /{command} is not implemented yet (target: {target}); refusing to pretend success (INV-003).")


def _cmd_help(echo: Callable[[str], None]) -> None:
    echo(
        "commands: /help /sessions [symbol] /show [id] /resume [id] "
        "/watch [list|add|remove ...] /sync [run|status] /tools [name [k=v ...]] /exit"
    )
    echo("not implemented yet (explicit failure): " + ", ".join(f"/{name}" for name in sorted(_NOT_IMPLEMENTED)))


def _cmd_sessions(store: SessionStore, args: list[str], echo: Callable[[str], None]) -> None:
    symbol = args[0] if args else None
    rows = store.list_sessions(symbol=symbol)
    if not rows:
        echo("no sessions match the filter")
        return
    for row in rows:
        symbols = ",".join(row["subject_symbols"]) or "-"
        echo(f"{row['session_id']}  {row['created']}  {row['status']}  {symbols}  {row['profile']}")


def build_registry(store: SessionStore, data_store: Any = None) -> Registry:
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

    The interactive confirmation happens here; the registry write gate
    opens only for calls carrying user_confirmed=true (INV-004).

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
        for i, cand in enumerate(candidates, start=1):
            echo(f"{i}) {cand['canonical_symbol']}  {cand['official_name']}  exchange {cand['exchange']}")
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
                arguments={"canonical_symbol": picked["canonical_symbol"], "user_confirmed": True},
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
                arguments={"canonical_symbol": rest[0], "user_confirmed": True},
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
        return
    if action != "run":
        echo(f"error: unknown sync action {action!r} (run | status)")
        return
    result = registry.execute(
        ToolCall(tool="sync.run", arguments={"user_confirmed": True}, call_id="slash-sync"),
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
    )


def start_new_session(
    store: SessionStore,
    *,
    profile: Profile | str = Profile.standard,
    data_root: "str | None" = None,
    data_store: Any = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
) -> None:
    """Create a session, stamp provenance, and run the interactive loop.

    The provider configuration is resolved once at session start and
    stamped into the session record (GOV-005); mid-session config
    changes do not affect an open session.

    Implements: REQ-SI-FR-013, REQ-SI-GOV-005 (ADR-001)
    """
    config = resolve_config(data_root)
    apply_budget_overrides(config.budgets)
    prompt_version, _identity = load_identity_prompt()
    stamp = {
        "model_id": config.chat_model,
        "provider_config": config.chat_base_url or "unconfigured-endpoint",
        "prompt_version": prompt_version,
    }
    record = store.create(profile=profile, provenance=stamp)
    echo(
        f"session {record['session_id']} opened (profile: {record['profile']}); type /help for commands, /exit to leave"
    )
    record = _session_loop(store, record, data_root=data_root, data_store=data_store, input_fn=input_fn, echo=echo)
    store.close(record["session_id"])
    echo(f"session {record['session_id']} closed")
    echo(f"resume with: stockinsider resume {record['session_id']}")


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
) -> None:
    """Resume a closed session (default: the most recent) and continue the loop.

    Prior turns are never rewritten: new turns append to the same
    session.jsonl (FR-023). Guardrail counters are per-process — a
    resumed session starts with fresh counters (documented v1
    limitation). The profile lock is validated on resume.

    Implements: REQ-SI-FR-023 (ADR-001)
    """
    target = session_id or _most_recent(store, closed_only=True)["session_id"]
    record = store.resume(target, profile=profile)
    restored = len(store.read_events(record["session_id"]))
    echo(
        f"session {record['session_id']} resumed (profile: {record['profile']}; "
        f"{restored} events restored); type /help for commands, /exit to leave"
    )
    record = _session_loop(store, record, data_root=data_root, data_store=data_store, input_fn=input_fn, echo=echo)
    store.close(record["session_id"])
    echo(f"session {record['session_id']} closed")
    echo(f"resume with: stockinsider resume {record['session_id']}")


def _session_loop(
    store: SessionStore,
    record: dict,
    *,
    data_root: "str | None" = None,
    data_store: Any = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
) -> dict:
    """Run the interactive loop; returns the FINAL bound record.

    /resume may switch the binding mid-loop; the returned record is
    the session the entry must close.

    Implements: REQ-SI-FR-013, REQ-SI-FR-023 (ADR-001)
    """
    config = resolve_config(data_root)
    apply_budget_overrides(config.budgets)
    registry = build_registry(store, data_store)
    engine = _build_engine(store, registry, config)
    while True:
        try:
            line = input_fn(PROMPT).strip()
        except EOFError:
            break
        if not line:
            continue
        if line == "/exit":
            break
        if line.startswith("/"):
            name, *args = line[1:].split()
            if name == "help":
                _cmd_help(echo)
            elif name == "sessions":
                _cmd_sessions(store, args, echo)
            elif name == "tools":
                _cmd_tools(registry, args, echo)
            elif name == "show":
                target = args[0] if args else record["session_id"]
                try:
                    render_session(store, target, echo)
                except SessionError as exc:
                    echo(f"error: {exc}")
            elif name == "watch":
                _cmd_watch(
                    registry,
                    args,
                    input_fn=input_fn,
                    echo=echo,
                )
            elif name == "sync":
                _cmd_sync(registry, args, echo)
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
                        echo("closed sessions (most recent first):")
                        for i, row in enumerate(closed, start=1):
                            symbols = ",".join(row["subject_symbols"]) or "-"
                            echo(f"  {i}) {row['session_id']}  {row['created']}  {row['profile']}  {symbols}")
                        choice = input_fn(f"select 1-{len(closed)} (enter=1, q=cancel): ").strip()
                        if choice.lower() == "q":
                            echo("resume cancelled")
                            continue
                        if choice == "":
                            choice = "1"
                        if not choice.isdigit() or not 1 <= int(choice) <= len(closed):
                            echo(f"error: invalid selection {choice!r}; resume cancelled")
                            continue
                        resolved = closed[int(choice) - 1]["session_id"]
                    if resolved == record["session_id"]:
                        echo("error: already in this session; /resume switches to a different closed session")
                        continue
                    store.close(record["session_id"])
                    echo(f"session {record['session_id']} closed (switching)")
                    record = store.resume(resolved)
                    engine = _build_engine(store, registry, config)
                    echo(
                        f"session {record['session_id']} resumed "
                        f"(profile: {record['profile']}; guardrail counters reset)"
                    )
                except SessionError as exc:
                    echo(f"error: {exc}")
            elif name in _NOT_IMPLEMENTED:
                _explicit_not_implemented(name, _NOT_IMPLEMENTED[name], echo)
            else:
                echo(f"error: unknown command /{name}; /help lists available commands")
        else:
            if engine is None:
                echo(
                    "error: provider unconfigured — run `stockinsider config set "
                    "--chat-base-url ...` and `--api-key` (or set PROVIDER_BASE_URL / "
                    f"{API_KEY_ENV}); slash commands remain available"
                )
            else:
                _run_conversational_turn(engine, record, line, echo)
    return record


def _build_engine(store: SessionStore, registry: Registry, config: ProviderConfig) -> TurnEngine | None:
    """Construct the turn engine when the provider is fully configured.

    Implements: REQ-SI-FR-008 (ADR-001)
    """
    key, _source = resolve_api_key()
    if not config.chat_base_url or key is None:
        return None
    provider = OpenAICompatibleProvider(config, api_key=key)
    return TurnEngine(store, registry, provider)


def _run_conversational_turn(engine: TurnEngine, record: dict, line: str, echo: Callable[[str], None]) -> None:
    """Run one free-text turn with streaming render and explicit failures.

    Implements: REQ-SI-FR-008, REQ-SI-FR-019 (ADR-001)
    """

    def _sink(piece: str) -> None:
        sys.stdout.write(piece)
        sys.stdout.flush()

    try:
        engine.run_turn(
            record["session_id"],
            line,
            profile=record["profile"],
            render=echo,
            progress=echo,
            stream_sink=_sink,
        )
    except KeyboardInterrupt:
        echo("\nturn interrupted")
    except ProviderError as exc:
        echo(f"error: {exc}")


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
            if original:
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
