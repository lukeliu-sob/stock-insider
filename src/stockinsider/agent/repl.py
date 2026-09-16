"""REPL loop and slash-command dispatch (blueprint §7.2-§7.3).

Slash commands and CLI subcommands are two entries to one verb set; a
third verb set is forbidden. Free-text turns fail explicitly until the
agent analysis loop lands (INV-003: refuse to pretend success).

Implements: REQ-SI-FR-013 (ADR-001)
"""

from __future__ import annotations

from collections.abc import Callable

from stockinsider.agent.profiles import Profile
from stockinsider.agent.session import SessionStore

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
    "tools": "tool registry (blueprint §4.1)",
}

_AGENT_LOOP_TARGET = "the agent analysis loop (agent runtime test plan)"


def _explicit_not_implemented(command: str, target: str, echo: Callable[[str], None]) -> None:
    echo(f"error: /{command} is not implemented yet (target: {target}); refusing to pretend success (INV-003).")


def _cmd_help(echo: Callable[[str], None]) -> None:
    echo("commands: /help /sessions [symbol] /exit")
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


def repl(
    store: SessionStore,
    *,
    profile: Profile | str = Profile.standard,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
) -> None:
    """Run the interactive REPL session loop.

    Implements: REQ-SI-FR-013 (ADR-001)
    """
    record = store.create(profile=profile)
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
