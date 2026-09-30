"""Agent turn engine: the conversation pipeline (blueprint §7.2).

One conversational turn: context assembly (identity prompt + bounded
history), a profile-capped tool loop through the registry membrane,
values-as-seen snapshotting (the INV-001 verification pool), the
guardrail post-check with quarantine/regeneration fallbacks, usage
accounting, and rendering. Everything injectable — offline tests run
the full pipeline with scripted providers.

Rendering contract (H1, 2026-09-29 audit): deltas buffer during the
turn and replay through stream_sink only after the numeric post-
check passes (verify-then-display; a quarantined turn never shows
its original text). render() is called exactly once per turn with
the final authoritative text; unchanged passing text is delivered
via the stream replay, changed text (quarantine, regeneration,
degradation, iteration-cap) via render().

Implements: REQ-SI-FR-008, REQ-SI-FR-019, REQ-SI-COST-002,
REQ-SI-INV-001, REQ-SI-INV-002, REQ-SI-GOV-003 (ADR-001)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stockinsider.agent.guardrail import PostCheckCounter, run_postcheck, run_with_regeneration
from stockinsider.agent.profiles import tool_loop_limit
from stockinsider.agent.registry import Registry
from stockinsider.agent.session import SessionStore
from stockinsider.agent.confirm import ConfirmationBroker
from stockinsider.shared.tools import EffectClass, ToolCall, ToolResult

#: Conversation-history window mapped into provider messages: the last
#: HISTORY_WINDOW user/assistant MESSAGES (10 turns). Fifth-audit fix
#: (TP-019, ADR-001 Am1): the window used to slice the last 20 EVENTS,
#: and tool calls/results are events too - a tool-using session kept
#: about three turns, and the slice could open mid-turn with an answer
#: whose question was cut off (the live model then denied having
#: stated a value it gave in turn 1).
HISTORY_WINDOW = 20

#: Told to the model when older turns fell outside the window, so it
#: says so instead of asserting what "the start" of the conversation was.
HISTORY_TRUNCATED_NOTE = (
    "[harness] Earlier turns of this session are outside your context window. "
    "If the user asks about them, say they are not in your context instead of "
    "guessing what was said."
)

RenderFn = Callable[[str], None]
ProgressFn = Callable[[str], None]
SinkFn = Callable[[str], None]


def _default_prompts_dir() -> Path:
    """The repository's prompts/ directory, package-root relative (low-3).

    Implements: REQ-SI-GOV-003 (ADR-001; TP-018 PR-3)
    """
    return Path(__file__).resolve().parents[3] / "prompts"


def load_identity_prompt(prompts_dir: Path | str | None = None) -> tuple[str, str]:
    """Load prompts/identity.md; return (version-stamp, body).

    The version stamp ("identity-v<N>") feeds the session provenance
    (GOV-003/GOV-005); prompt changes are eval-gated by CI. The default
    directory resolves relative to the package root (low-3, TP-018):
    the old cwd-relative default broke when the loop ran from any
    other directory.

    Implements: REQ-SI-GOV-003 (ADR-001)
    """
    directory = Path(prompts_dir) if prompts_dir is not None else _default_prompts_dir()
    path = directory / "identity.md"
    if not path.exists():
        raise FileNotFoundError(f"identity prompt missing: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"identity prompt missing front-matter: {path}")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError(f"identity prompt front-matter unterminated: {path}")
    version: str | None = None
    for line in text[3:end].splitlines():
        if line.strip().startswith("version:"):
            version = line.partition(":")[2].strip()
    if not version:
        raise ValueError(f"identity prompt front-matter missing version: {path}")
    body = text[end + 4 :].lstrip("\n")
    return f"identity-v{version}", body


@dataclass
class TurnOutcome:
    """One conversational turn's visible result and bookkeeping.

    Implements: REQ-SI-FR-008 (ADR-001)
    """

    displayed: str
    quarantined: bool
    aborted: str | None
    tools_used: int
    usage: dict[str, int] = field(default_factory=dict)
    #: the answer without its pre-tool prelude (TP-019; /report stores it)
    body: str = ""
    #: True when INV-002 refused the answer after the one regeneration
    refused: bool = False


def _accumulate(total: dict[str, int], usage: dict[str, int]) -> None:
    for key, value in usage.items():
        total[key] = total.get(key, 0) + value


class TurnEngine:
    """Runs conversational turns through the full §7.2 pipeline.

    Implements: REQ-SI-FR-008, REQ-SI-FR-019 (ADR-001)
    """

    def __init__(
        self,
        store: SessionStore,
        registry: Registry,
        provider: Any,
        *,
        prompts_dir: Path | str | None = None,
    ) -> None:
        """Bind the store, registry membrane, and provider; load the identity prompt."""
        self._aborted: str | None = None  # H4: sticky session abort
        self.confirmations = ConfirmationBroker()  # H3: write-token broker
        self._ledgers: dict[str, dict[str, Any]] = {}  # cross-turn INV-001 pools

        self._store = store
        self._registry = registry

        self._provider = provider
        self._prompt_version, self._identity = load_identity_prompt(prompts_dir)
        self._counter = PostCheckCounter()

    @property
    def prompt_version(self) -> str:
        """The stamped prompt version.

        Implements: REQ-SI-GOV-003 (ADR-001)
        """
        return self._prompt_version

    def _session_ledger(self, session_id: str) -> dict[str, Any]:
        """The session-wide provenance ledger (loaded from turn snapshots).

        Implements: REQ-SI-INV-001 (ADR-001; TP-017 PR-3a)
        """
        if session_id not in self._ledgers:
            merged: dict[str, Any] = {}
            for _turn, values in self._store.load_snapshots(session_id):
                merged.update(values)
            self._ledgers[session_id] = merged
        return self._ledgers[session_id]

    @property
    def registry(self) -> Registry:
        """Public read access for the confirmation replay path (H3).

        Implements: REQ-SI-INV-004 (ADR-005; TP-017 PR-2)
        """
        return self._registry

    def _next_turn_id(self, session_id: str) -> str:
        """Derive the next turn id from the session's existing events (resume-safe).

        Implements: REQ-SI-FR-011, REQ-SI-FR-023 (ADR-001)
        """
        numbers = []
        for event in self._store.read_events(session_id):
            turn = event.get("turn")
            if isinstance(turn, str) and turn.startswith("turn-") and turn[5:].isdigit():
                numbers.append(int(turn[5:]))
        return f"turn-{max(numbers, default=0) + 1:04d}"

    def _history_messages(self, session_id: str) -> list[dict[str, str]]:
        """Prior user/assistant messages, windowed by MESSAGES (TP-019).

        Tool events never consume the window; the window never opens on
        an assistant message whose question was cut off; truncation is
        announced to the model instead of left for it to guess.

        Implements: REQ-SI-FR-011, REQ-SI-COST-001 (ADR-001 Am1; TP-019)
        """
        conversational = [
            event
            for event in self._store.read_events(session_id)
            if event.get("event") in ("user-message", "assistant-message")
        ]
        window = conversational[-HISTORY_WINDOW:]
        while window and window[0].get("event") != "user-message":
            window = window[1:]
        messages: list[dict[str, str]] = []
        if len(window) < len(conversational):
            messages.append({"role": "system", "content": HISTORY_TRUNCATED_NOTE})
        for event in window:
            role = "user" if event.get("event") == "user-message" else "assistant"
            content = event.get("text", "")
            if role == "assistant" and event.get("post_check") == "failed":
                # TP-019: the degraded line "data unavailable for: 10"
                # read back as the model's own answer made it conclude
                # the DATA was unavailable (live run); it is told what
                # actually happened instead.
                content = (
                    "[harness] This answer was withheld by the numeric post-check "
                    "(INV-001): it cited numbers not found in the tool results. "
                    f"The user saw only: {content}"
                )
            messages.append({"role": role, "content": content})
        return messages

    def run_turn(
        self,
        session_id: str,
        user_text: str,
        *,
        profile: str,
        render: RenderFn,
        progress: ProgressFn,
        stream_sink: SinkFn | None = None,
    ) -> TurnOutcome:
        """Run one full turn; content failures degrade, never crash (INV-003).

        Implements: REQ-SI-FR-008, REQ-SI-FR-019, REQ-SI-COST-002,
        REQ-SI-INV-001, REQ-SI-INV-002 (ADR-001)
        """
        if getattr(self, "_aborted", None):
            refusal = (
                f"session aborted ({self._aborted} threshold): this session no longer "
                "calls the model; start a new session (INV-003 — explicit, not silent)"
            )
            render(refusal)
            progress(_footer(0, None, {}))
            return TurnOutcome(
                displayed=refusal,
                quarantined=False,
                aborted=self._aborted,
                tools_used=0,
                usage={},
            )
        turn_id = self._next_turn_id(session_id)
        # H3-5 (TP-018): stale confirmation tokens age out at every turn
        # boundary; they no longer linger for the whole process lifetime.
        self.confirmations.expire_turns(_turn_number(turn_id))
        # M6 (2026-09-29 audit): read history BEFORE appending this turn's
        # user event — the old order duplicated the current message into
        # the model context (the model literally saw it twice).
        history = self._history_messages(session_id)
        self._store.append_event(session_id, {"event": "user-message", "text": user_text, "turn": turn_id})
        usage_total: dict[str, int] = {}
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._identity},
            *history,
            {"role": "user", "content": user_text},
        ]
        tool_specs = self._registry.openai_tool_specs()
        wire_map = {spec["function"]["name"]: spec["function"]["name"] for spec in tool_specs}
        for spec in self._registry.list_tools():
            from stockinsider.agent.registry import wire_name

            wire_map[wire_name(spec.name)] = spec.name
        limit = tool_loop_limit(profile)
        candidate = ""
        # H1 residual (TP-018): provider text emitted BEFORE tool calls in
        # this same turn accumulates as prelude. The post-check validates
        # prelude + candidate as one string — nothing the user sees on
        # the replay path bypasses INV-001, and the assistant-message
        # event stores the same full text (screen == record).
        preludes: list[str] = []
        tools_used = 0
        snapshot_values: dict[str, Any] = {}
        call_seq = 0
        # H1 (2026-09-29 audit): verify-then-display. Deltas buffer in the
        # deferred sink and replay to the user's sink ONLY after the post-
        # check passes; a quarantined turn never shows its original text.
        deferred = _DeferredSink()
        provider_sink = deferred.push if stream_sink is not None else None
        for _iteration in range(limit):
            outcome = self._provider.complete(messages, tools=tool_specs, stream_sink=provider_sink)
            _accumulate(usage_total, outcome.usage)
            if outcome.tool_calls:
                if outcome.text.strip():
                    preludes.append(outcome.text.strip())
                    if provider_sink is not None:
                        # screen == record (TP-019): the record joins the
                        # prelude and the final text with a newline; the
                        # replayed deltas used to run them together
                        # ("...for 0700.HK.Watchlist update first").
                        provider_sink("\n")
                messages.append({"role": "assistant", "tool_calls": outcome.tool_calls})
                for call in outcome.tool_calls:
                    function = call.get("function") or {}
                    raw_name = function.get("name") or call.get("name", "")
                    name = wire_map.get(raw_name, raw_name)
                    raw_arguments = function.get("arguments", call.get("arguments", "{}"))
                    try:
                        arguments = json.loads(raw_arguments or "{}")
                    except json.JSONDecodeError:
                        # low-1 (TP-018): a malformed argument payload is an
                        # explicit tool failure — never a silent {} execution
                        # (empty defaults could fire wrong-path effects).
                        arguments = None
                    if arguments is None:
                        result = ToolResult(
                            call_id=call.get("id") or turn_id,
                            ok=False,
                            error=(
                                "malformed tool arguments (not JSON): "
                                f"{str(raw_arguments)[:120]!r} (INV-003)"
                            ),
                        )
                    else:
                        # H3 (TP-018): the conversational path NEVER sets
                        # allow_write — the model's assertions are not consent.
                        # Write-class calls are intercepted: a one-time token
                        # is issued and the pending write renders to the HUMAN
                        # directly through progress chrome. The token never
                        # travels through model text (ADR-005 Am3 non-relay
                        # principle): INV-001 would quarantine a relayed
                        # digit-bearing token, and the user would never see it.
                        _effect = getattr(self._registry, "effect_class", lambda _n: None)(name)
                        if _effect is EffectClass.WRITE:
                            token = self.confirmations.issue(
                                session_id, name, arguments, turn=_turn_number(turn_id)
                            )
                            progress(
                                f"pending write confirmation: {name} "
                                f"{json.dumps(arguments, sort_keys=True)} -- reply "
                                f"'confirm {token}' to execute, anything else to ignore"
                            )
                            result = ToolResult(
                                call_id=call.get("id") or turn_id,
                                ok=False,
                                error=(
                                    "write gate: human confirmation required. The "
                                    "harness shows the user a one-time confirmation "
                                    "prompt in the terminal — do NOT repeat or invent "
                                    "the token; ask the user to confirm there."
                                ),
                            )
                        else:
                            result = self._registry.execute(
                                ToolCall(tool=name, arguments=arguments, call_id=call.get("id") or turn_id),
                                allow_write=False,
                            )
                    tools_used += 1
                    self._store.append_event(
                        session_id,
                        {"event": "tool-call", "tool": name, "arguments": arguments, "turn": turn_id},
                    )
                    result_event: dict[str, Any] = {
                        "event": "tool-result",
                        "tool": name,
                        "ok": result.ok,
                        "result": result.result,
                        "provenance": result.provenance,
                        "turn": turn_id,
                    }
                    if not result.ok:
                        # INV-003: the log states WHY a tool failed (write
                        # gate, malformed arguments, unknown tool) instead
                        # of recording a bare null.
                        result_event["error"] = result.error
                    self._store.append_event(session_id, result_event)
                    marker = "ok" if result.ok else "failed"
                    source = result.provenance.get("source_kind", "error") if result.ok else "error"
                    progress(f"· {name} … {marker} ({source})")
                    payload: Any = result.result if result.ok else {"error": result.error}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id") or name,
                            "content": json.dumps(payload),
                        }
                    )
                    if result.ok:
                        # BD-019 + M5 residual (TP-018): the key carries the
                        # TURN as well as the per-turn call sequence — a later
                        # turn's market.quote#1 used to evict an earlier
                        # turn's from the session ledger (BD-019 at session
                        # scope); citations of first-turn evidence no longer
                        # quarantine spuriously after a second symbol is
                        # queried.
                        call_seq += 1
                        snapshot_values[f"{turn_id}/{name}#{call_seq}"] = result.result
                continue
            candidate = outcome.text
            break
        else:
            stop = (
                f"turn stopped: tool-loop iteration cap ({limit}) reached for profile "
                f"{profile}; no response was fabricated (INV-003)"
            )
            self._store.append_event(session_id, {"event": "error", "kind": "iteration-cap", "turn": turn_id})
            render(stop)
            progress(_footer(tools_used, None, usage_total))
            return TurnOutcome(
                displayed=stop,
                quarantined=False,
                aborted=None,
                tools_used=tools_used,
                usage=dict(usage_total),
            )

        # values-as-seen snapshot: this turn's artifact stays per-turn;
        # the INV-001 pool spans the SESSION (cross-turn ledger, TP-017
        # PR-3a) — a restated earlier number is a legitimate citation of
        # evidence the session already holds (with turn attribution in
        # the artifact files).
        self._store.snapshot(session_id, turn_id, snapshot_values)
        ledger = self._session_ledger(session_id)
        ledger.update(snapshot_values)
        # H1 residual (TP-018): the CHECKED string is everything the user
        # will see on the replay path — pre-tool-call prelude text plus
        # the final candidate. Fabricated numbers in opening prose used to
        # stream through unvalidated (and never entered session.jsonl).
        combined = "\n".join([*preludes, candidate]) if preludes else candidate
        verdict = run_postcheck(combined, ledger)

        def _replay() -> None:
            if stream_sink is not None:
                for piece in deferred.buffer:
                    stream_sink(piece)
                stream_sink("\n")

        # body: the answer without the pre-tool prelude (what /report
        # persists, TP-019); refused: the INV-002 refusal summary is the
        # answer (a report gate must not store it as a report).
        refused = False
        if verdict.quarantined:
            self._store.append_event(
                session_id,
                {
                    "event": "error",
                    "kind": "post-check",
                    "post_check": "failed",
                    "original": combined,
                    "turn": turn_id,
                },
            )
            # quarantined: the buffered original is discarded, never shown
            render(verdict.display_text)
            displayed = verdict.display_text
            body = displayed
        elif verdict.epistemic.violations:

            # H1 residual (TP-018b, fourth audit): the regeneration used
            # to stream through the RAW user sink - fabricated numbers
            # showed on screen before the recheck, and a passing
            # regeneration displayed twice (streamed, then rendered).
            # The regeneration buffers in its OWN deferred sink and is
            # replayed only after the numeric recheck passes.
            regen_sink = _DeferredSink()
            original_violations = list(verdict.epistemic.violations)

            def _regenerator(reminder_text: str) -> str:
                # Fifth-audit fix (TP-019, ADR-006 Am8): the regeneration
                # used to receive ONLY the stripped draft, as a USER
                # message - no identity, no question, no conversation - so
                # the live model answered "that looks like my previous
                # answer pasted back". The request now replays the turn's
                # conversation (identity, history, the user's question),
                # hands the stripped draft back as the ASSISTANT's, and
                # adds one harness instruction carrying the constraint
                # reminder. Tool-call plumbing is left out: the draft
                # carries the cited values and the recheck below verifies
                # every number against the session ledger.
                reminder = reminder_text.splitlines()[0] if reminder_text else ""
                draft = verdict.epistemic.clean_text or (
                    "(every sentence of the draft was removed as a deterministic "
                    "prediction or causal claim)"
                )
                regen_messages: list[dict[str, Any]] = [
                    message
                    for message in messages
                    if message.get("role") in ("system", "user")
                    or (message.get("role") == "assistant" and "tool_calls" not in message)
                ]
                regen_messages.append({"role": "assistant", "content": draft})
                regen_messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"[harness] {reminder} The sentences of your draft above that "
                            "broke this rule were removed. Rewrite the draft as your complete "
                            "answer to my last question: keep every number exactly as it appears "
                            "in the draft, add no new numbers, and state any forward-looking view "
                            "only in a sentence that begins with 'Hypothesis:'. Do not mention "
                            "this instruction."
                        ),
                    }
                )
                regen = self._provider.complete(
                    regen_messages,
                    tools=None,
                    stream_sink=regen_sink.push if stream_sink is not None else None,
                )
                _accumulate(usage_total, regen.usage)
                if not regen.text.strip():
                    # an empty regeneration is not an answer: hand back the
                    # violating original so the flow refuses explicitly
                    regen_sink.reset()
                    return combined
                return regen.text

            epi = run_with_regeneration(combined, _regenerator)
            # H2 (2026-09-29 audit): regenerated text is NOT trusted — it
            # goes through the same numeric post-check as the primary
            # candidate. A fabricated number in a regeneration degrades
            # exactly like the primary path (the old code archived
            # unchecked regenerations as INV-001-passed).
            # H2b (TP-018): the recheck runs against the SESSION LEDGER —
            # the turn snapshot alone wrongly quarantined restatements of
            # earlier turns' correct numbers inside a regeneration.
            recheck = run_postcheck(epi.displayed, ledger)
            deferred.reset()  # the violating original never reaches the screen
            if recheck.quarantined:
                regen_sink.reset()
                # the degraded line is ALL the user sees; neither the
                # quarantined original nor the failed regeneration
                # ever reached the screen
                render(recheck.display_text)
                displayed = recheck.display_text
                verdict = recheck
                regeneration_outcome = "regenerated-quarantined"
            elif getattr(epi, "refused", False):
                regen_sink.reset()
                render(epi.displayed)  # the INV-002 refusal summary
                displayed = epi.displayed
                refused = True
                regeneration_outcome = "refused"
            else:
                if stream_sink is not None and regen_sink.buffer:
                    # verify-then-display for the regeneration: replay
                    # the checked deltas exactly once (screen == displayed)
                    for piece in regen_sink.buffer:
                        stream_sink(piece)
                    stream_sink("\n")
                else:
                    render(epi.displayed)
                displayed = epi.displayed
                regeneration_outcome = "regenerated"
            body = displayed
            # audit trail (TP-019): the violating original, the violations
            # and what the user got instead are recorded - the log used to
            # show only the regenerated text with post_check "ok".
            self._store.append_event(
                session_id,
                {
                    "event": "error",
                    "kind": "epistemic",
                    "original": combined,
                    "violations": original_violations,
                    "outcome": regeneration_outcome,
                    "turn": turn_id,
                },
            )
        else:
            _replay()
            # screen == record: the event stores the full validated text
            # (prelude included), exactly what the replay displayed.
            displayed = combined
            body = candidate
        self._store.append_event(
            session_id,
            {
                "event": "assistant-message",
                "text": displayed,
                "turn": turn_id,
                "post_check": "failed" if verdict.quarantined else "ok",
                "usage": dict(usage_total),
            },
        )
        abort_reason = self._counter.record(verdict)
        if abort_reason:
            # H4: the abort is now session-sticky — the next run_turn refuses
            # before any model call (the old code only printed a line).
            self._aborted = abort_reason
            # H4 residual (TP-018): the state also persists in the session
            # index; resume() refuses aborted sessions, so restarting the
            # process no longer resets the counters (close() will not
            # downgrade the status).
            self._store.abort(session_id, abort_reason)
            render(f"session aborted: {abort_reason} threshold reached (invariant fallback)")
        progress(_footer(tools_used, verdict.quarantined, usage_total))
        return TurnOutcome(
            displayed=displayed,
            quarantined=verdict.quarantined,
            aborted=abort_reason,
            tools_used=tools_used,
            usage=dict(usage_total),
            body=body,
            refused=refused,
        )


def _turn_number(turn_id: str) -> int:
    """Numeric part of a turn id (turn-0007 -> 7); 0 when unparseable."""
    digits = "".join(ch for ch in turn_id if ch.isdigit())
    return int(digits) if digits else 0


class _DeferredSink:
    """Buffers provider deltas for verify-then-display (H1).

    Implements: REQ-SI-INV-001, REQ-SI-FR-019 (ADR-001; TP-017 PR-1)
    """

    def __init__(self) -> None:
        self.buffer: list[str] = []

    def push(self, piece: str) -> None:
        """Accumulate one delta; nothing is displayed here.

        Implements: REQ-SI-FR-019 (ADR-001; TP-017 PR-1)
        """
        self.buffer.append(piece)

    def reset(self) -> None:
        """Discard the buffered original (quarantine/regeneration paths).

        Implements: REQ-SI-INV-001 (ADR-001; TP-017 PR-1)
        """
        self.buffer.clear()


def _footer(tools_used: int, quarantined: bool | None, usage: dict[str, int]) -> str:
    total = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
    state = "n/a" if quarantined is None else ("failed" if quarantined else "pass")
    return f"(tools: {tools_used} · post-check: {state} · tokens: {total})"
