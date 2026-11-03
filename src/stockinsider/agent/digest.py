"""Weekly digest per watchlist symbol (FR-016).

Facts come only through registry tools and are logged and snapshotted
like any turn's, so the digest is a replayable session. The
deterministic sections are rendered from those results and pass the
INV-001 post-check against them; sections without data say so
explicitly (INV-003). A configured chat provider adds one narration
turn per symbol through the ordinary turn engine.

Implements: REQ-SI-FR-016, REQ-SI-INV-001, REQ-SI-INV-003 (ADR-001, ADR-005 Am5; TP-043)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stockinsider.agent import guardrail
from stockinsider.agent.loop import load_identity_prompt
from stockinsider.agent.profiles import Profile, apply_budget_overrides
from stockinsider.agent.providers import resolve_config
from stockinsider.agent.repl import PlainIO, _build_engine, _run_conversational_turn, build_registry
from stockinsider.agent.session import SessionStore
from stockinsider.shared.tools import ToolCall

#: The digest's week: the 5-session window of market.performance.
WEEK_SESSIONS = 5
EVENTS_UNAVAILABLE = "unavailable: event scoring (REQ-SI-FR-009) is not implemented, so no scored events exist"
CATALYSTS_UNAVAILABLE = (
    "unavailable: no earnings calendar is ingested (the fundamentals feed is not in the current vendor plan)"
)
NARRATION_UNCONFIGURED = (
    "unavailable: chat provider unconfigured (set PROVIDER_API_KEY and the chat base_url); "
    "the sections above are complete without it"
)


@dataclass
class DigestOutcome:
    """What one digest run produced (FR-016).

    Implements: REQ-SI-FR-016 (ADR-001; TP-043)
    """

    session_id: str | None
    artifact: str | None
    text: str
    symbols: list[str] = field(default_factory=list)
    #: symbols whose price section is unavailable (the CLI exits 1)
    failed: list[str] = field(default_factory=list)


def _next_turn_id(store: SessionStore, session_id: str) -> str:
    numbers = [
        int(turn[5:])
        for event in store.read_events(session_id)
        if isinstance(turn := event.get("turn"), str) and turn.startswith("turn-") and turn[5:].isdigit()
    ]
    return f"turn-{max(numbers, default=0) + 1:04d}"


def _gather(store: SessionStore, registry: Any, session_id: str, symbol: str) -> tuple[dict, dict[str, Any]]:
    """Run the fact tools for one symbol; log and snapshot them like an engine turn."""
    turn_id = _next_turn_id(store, session_id)
    store.append_event(
        session_id,
        {"event": "user-message", "text": f"[harness] weekly digest: deterministic facts for {symbol}", "turn": turn_id},
    )
    snapshot: dict[str, Any] = {}
    results: dict[str, Any] = {}
    calls = (
        ("market.quote", {"symbol": symbol}),
        ("market.performance", {"symbol": symbol}),
        ("news.recent", {"symbol": symbol, "k": 10}),
    )
    for seq, (tool, arguments) in enumerate(calls, start=1):
        result = registry.execute(ToolCall(tool=tool, arguments=arguments, call_id=f"digest-{turn_id}-{seq}"))
        store.append_event(session_id, {"event": "tool-call", "tool": tool, "arguments": arguments, "turn": turn_id})
        event: dict[str, Any] = {
            "event": "tool-result",
            "tool": tool,
            "ok": result.ok,
            "result": result.result,
            "provenance": result.provenance,
            "turn": turn_id,
        }
        if not result.ok:
            event["error"] = result.error
        store.append_event(session_id, event)
        results[tool] = result
        if result.ok:
            snapshot[f"{turn_id}/{tool}#{seq}"] = result.result
    store.snapshot(session_id, turn_id, snapshot)
    return snapshot, results


def _signed(value: float) -> str:
    return f"+{value}" if value > 0 else str(value)


def _section(symbol: str, results: dict[str, Any]) -> tuple[list[str], bool]:
    """The deterministic lines for one symbol, and whether its price section is available."""
    quote, performance, news = results["market.quote"], results["market.performance"], results["news.recent"]
    name = None
    for result in (quote, performance, news):
        if result.ok and isinstance(result.result, dict) and result.result.get("official_name"):
            name = result.result["official_name"]
            break
    lines = [f"## {symbol}" + (f" — {name}" if name else "")]
    if quote.ok:
        bar = quote.result
        lines.append(f"- latest bar: {bar['date']}, close {bar['close']} {bar.get('currency') or ''}".rstrip())
    else:
        lines.append(f"- latest bar: unavailable: {quote.error}")
    week = None
    if performance.ok:
        week = next((row for row in performance.result["windows"] if row["sessions"] == WEEK_SESSIONS), None)
        if week is not None:
            lines.append(
                f"- week ({week['sessions']} sessions, {week['from_date']} to {week['to_date']}): adjusted close "
                f"{week['from_adjusted_close']} to {week['adjusted_close']}, change {_signed(week['change_pct'])}%"
            )
        else:
            reason = next(
                (u["reason"] for u in performance.result["unavailable"] if u["sessions"] == WEEK_SESSIONS),
                "the week window is missing from the tool result",
            )
            lines.append(f"- week: unavailable: {reason}")
    else:
        lines.append(f"- week: unavailable: {performance.error}")
    if news.ok:
        since = week["from_date"] if week is not None else None
        items = [
            item
            for item in news.result.get("items", [])
            if since is None or str(item.get("seendate", ""))[:10] >= since
        ]
        if items:
            # No count here: the in-week subset is derived, and no tool states it (INV-001).
            lines.append("- headlines this week:")
            lines += [f'  - "{item["title"]}" ({str(item.get("seendate", ""))[:10]})' for item in items]
        else:
            lines.append("- headlines this week: unavailable: no stored headline falls within the week window")
    else:
        lines.append(f"- headlines this week: unavailable: {news.error}")
    lines.append(f"- scored events: {EVENTS_UNAVAILABLE}")
    lines.append(f"- upcoming catalysts: {CATALYSTS_UNAVAILABLE}")
    return lines, week is not None


def _narrate(engine: Any, record: dict, symbol: str) -> str:
    """One narration turn through the ordinary engine (post-check included)."""
    instruction = (
        f"Write a two-to-four sentence narration of this week's digest for {symbol}. Use only the facts this "
        "session already holds for it (market.quote, market.performance and news.recent; call them again if "
        "you need to). Cite every number exactly as the tools returned it, with its date or window. Make no "
        "forecast or causal claim; label any interpretation as a hypothesis (INV-002). Output only the narration."
    )
    outcome = _run_conversational_turn(engine, record, instruction, PlainIO(echo=lambda _line: None))
    if outcome is None:
        return "unavailable: the narration turn did not complete (see the session log)"
    if getattr(outcome, "quarantined", False) or getattr(outcome, "aborted", None):
        return "unavailable: the narration failed the INV-001 post-check"
    if getattr(outcome, "refused", False):
        return "unavailable: the narration was refused by the epistemic filter (INV-002)"
    text = (getattr(outcome, "body", "") or getattr(outcome, "displayed", "")).strip()
    return text or "unavailable: the narration was empty"


def run_digest(
    store: SessionStore,
    *,
    data_store: Any,
    data_root: str | None = None,
    echo: Callable[[str], None] = print,
    engine_factory: Callable[[SessionStore, Any], Any] | None = None,
) -> DigestOutcome:
    """Generate, store and print the weekly digest for every watchlist symbol.

    Implements: REQ-SI-FR-016, REQ-SI-INV-001, REQ-SI-INV-003, REQ-SI-GOV-005 (ADR-001; TP-043)
    """
    registry = build_registry(store, data_store=data_store)
    listed = registry.execute(ToolCall(tool="watchlist.list", arguments={}, call_id="digest-watchlist"))
    if not listed.ok:
        text = f"error: digest needs the watchlist: {listed.error}"
        echo(text)
        return DigestOutcome(None, None, text, failed=["<watchlist>"])
    symbols = [row["canonical_symbol"] for row in listed.result or []]
    if not symbols:
        text = "watchlist is empty; nothing to digest"
        echo(text)
        return DigestOutcome(None, None, text)
    config = resolve_config(data_root)
    apply_budget_overrides(config.budgets)
    prompt_version, _identity = load_identity_prompt()
    record = store.create(
        profile=Profile.standard,
        provenance={
            "model_id": config.chat_model,
            "provider_config": config.chat_base_url or "unconfigured-endpoint",
            "prompt_version": prompt_version,
        },
    )
    engine = (engine_factory or (lambda s, r: _build_engine(s, r, config)))(store, registry)
    specs = {spec.name: spec for spec in registry.list_tools()}
    generated = datetime.now(timezone.utc).date().isoformat()
    body: list[str] = [f"# Weekly digest — {generated}", "", f"- session: {record['session_id']}", ""]
    failed: list[str] = []
    for symbol in symbols:
        snapshot, results = _gather(store, registry, record["session_id"], symbol)
        lines, priced = _section(symbol, results)
        if not priced:
            failed.append(symbol)
        section = "\n".join(lines)
        # FR-016 fit criterion: the deterministic text passes the same
        # INV-001 post-check as any answer; a miss is marked, never hidden.
        verdict = guardrail.postcheck_numbers(section, snapshot, specs)
        body.append(guardrail.mark_claims(section, verdict) if not verdict.passed else section)
        narration = _narrate(engine, record, symbol) if engine is not None else NARRATION_UNCONFIGURED
        body += [f"- narration: {narration}", ""]
    text = "\n".join(body).rstrip() + "\n"
    path = store.artifact(record["session_id"], f"digest-{generated}.md", text)
    store.close(record["session_id"])
    echo(text.rstrip())
    echo(f"digest stored: {path.name} (session {record['session_id']})")
    return DigestOutcome(record["session_id"], path.name, text, symbols, failed)
