"""REPL loop and slash-command dispatch (blueprint §7.2-§7.3).

Slash commands and CLI subcommands are two entries to one verb set; a
third verb set is forbidden. /tools lists the registry and directly
invokes deterministic read/compute tools through the same membrane the
agent loop will use. Free-text turns fail explicitly until the agent
analysis loop lands (INV-003: refuse to pretend success).

Implements: REQ-SI-FR-013, REQ-SI-INV-003 (ADR-001, ADR-005)
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from stockinsider.agent.context import estimate_tokens
from stockinsider.agent.profiles import Profile, apply_budget_overrides, envelope_for
from stockinsider.agent.providers import resolve_config
from stockinsider.agent.registry import Registry
from stockinsider.agent.session import SessionStore
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
    "resume": "REQ-SI-FR-023",
    "show": "REQ-SI-FR-022",
    "watch": "REQ-SI-FR-004",
    "sync": "REQ-SI-FR-001",
    "config": "REQ-SI-FR-021",
    "compact": "context compaction (blueprint §7.4)",
}

_AGENT_LOOP_TARGET = "the agent analysis loop (agent runtime test plan)"


def _explicit_not_implemented(command: str, target: str, echo: Callable[[str], None]) -> None:
    echo(f"error: /{command} is not implemented yet (target: {target}); refusing to pretend success (INV-003).")


def _cmd_help(echo: Callable[[str], None]) -> None:
    echo("commands: /help /sessions [symbol] /tools [name [k=v ...]] /exit")
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


def build_registry(store: SessionStore) -> Registry:
    """Register the default deterministic tool set (ADR-005).

    Handlers are closures over existing agent modules; the registry
    itself stays free of non-shared imports (dependency law).

    Implements: REQ-SI-FR-013 (ADR-005)
    """
    registry = Registry()
    registry.register(
        ToolSpec(
            name="budget.query",
            description="Context budget envelope for an analysis profile.",
            arguments_spec={"profile": "str"},
            result_spec="dict",
            effect_class=EffectClass.COMPUTE,
            source_kind=SourceKind.COMPUTED,
        ),
        lambda args: _budget_query(args),
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
            f"ok: {result.result} "
            f"(provenance: {result.provenance['source_kind']} @ {result.provenance['produced_at']})"
        )
    else:
        echo(f"error: {result.error}")


def repl(
    store: SessionStore,
    *,
    profile: Profile | str = Profile.standard,
    data_root: "str | None" = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
) -> None:
    """Run the interactive REPL session loop.

    The provider configuration is resolved once at session start and
    stamped into the session record (GOV-005); mid-session config
    changes do not affect an open session.

    Implements: REQ-SI-FR-013, REQ-SI-GOV-005 (ADR-001)
    """
    config = resolve_config(data_root)
    apply_budget_overrides(config.budgets)
    stamp = {
        "model_id": config.chat_model,
        "provider_config": config.chat_base_url or "unconfigured-endpoint",
    }
    record = store.create(profile=profile, provenance=stamp)
    registry = build_registry(store)
    echo(
        f"session {record['session_id']} opened (profile: {record['profile']}); type /help for commands, /exit to leave"
    )
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
            elif name in _NOT_IMPLEMENTED:
                _explicit_not_implemented(name, _NOT_IMPLEMENTED[name], echo)
            else:
                echo(f"error: unknown command /{name}; /help lists available commands")
        else:
            echo(
                f"error: {_AGENT_LOOP_TARGET} is not implemented; this REPL handles "
                "slash commands only - refusing to pretend success (INV-003)."
            )
    store.close(record["session_id"])
    echo(f"session {record['session_id']} closed")
