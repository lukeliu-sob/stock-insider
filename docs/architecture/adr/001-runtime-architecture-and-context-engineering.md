# ADR-001 — Runtime Architecture and Context Engineering

| Field | Value |
|---|---|
| ID | ADR-001 |
| Status | Accepted |
| Date | 2026-09-15 |
| Registry baseline | `docs/req/requirements.yaml` v0.3.1 |
| Governs | Elaboration of `architecture-blueprint.md` §4 (boundaries), §5 (components), §7 (workflow), §8 (context engineering) |
| Related | ADR-002 (data vendor), ADR-003 (storage); glossary terms *Provenance Ledger*, *Model Routing* |

## 1. Decision

Adopt a two-part runtime architecture:

1. **Agent side** — a self-built, lightweight agent loop (REPL + turn pipeline), organized as `agent/` (`repl`, `session`, `context`, `guardrail`, `registry`, `providers`). No third-party agent framework.
2. **Data side** — an in-process Python package (`data/`: `ingest`, `store`, `compute`, `quant`) behind a facade, consumed exclusively through the tool registry.

The tool registry is the single authority membrane between the two parts (blueprint §4.1): the LLM never touches storage, network, or computation directly; every tool declares input/output schemas, an effect class, a provenance stamping rule, and fail-closed semantics.

Architectural patterns are borrowed deliberately from mature harnesses — session persistence as append-only JSONL, provider abstraction, tool permission gates, context compaction (opencode-style) — but no runtime code depends on any harness.

## 2. Alternatives Considered

| Decision point | Alternatives | Rejected because |
|---|---|---|
| Agent runtime | LangGraph / pydantic-ai / smolagents | Framework version lock-in; hides the context pipeline the course requires us to govern; hidden-dependency debt; our loop is small (tool dispatch + context assembly). |
| Topology | Local HTTP/gRPC service for the data side | Single-user CLI; a daemon adds deployment and failure modes with no consumer. The facade seam preserves future extraction at one-module cost. |
| Data access | LLM-generated SQL over the database | Violates INV-001/INV-003 verifiability and SEC-002 layered defense; schema-validated tools are the only defensible boundary. |
| Session state | In-place mutable session files; database-only state | Violates append-only audit discipline (FR-011); folders give per-session portability, the database gives the index — both, via the sessions index. |

## 3. Consequences

**Positive**: full control of the context pipeline (token budgets, compaction, re-injection — §6); every component testable in isolation; zero framework upgrade pressure; offline tests mock a single provider interface (FR-021).

**Negative / accepted costs**: we own the loop code and its edge cases (streaming errors, partial tool calls, resume consistency); no framework community patches; context engineering is disciplined by this ADR rather than inherited from a framework.

## 4. Reopen Conditions

- A framework offers verifiable guardrail hooks and enforceable context budgets we cannot replicate cheaply → runtime reopen.
- Multi-user or remote access becomes a requirement → topology reopen.
- The loop exceeds ~1k lines or needs multi-agent coordination (methodology risk B-14) → registry/loop reopen.

## 5. Architectural Design Process (audit summary)

Six owner-supervised discussion rounds produced this architecture:

| Round | Outcome |
|---|---|
| R1 | Problem framing; three feature domains (data display, analysis, traceability). |
| R2 | Anti-hallucination mechanisms (provenance types, compute/say separation); event-study pipeline; storage split (structured vs. vector). |
| R3 | Multi-market implications (HK+US): symbology, calendars, currencies; watchlist mode. |
| R4 | English-only policy; API-only models with user-configurable providers; analysis profiles; performance deferral (streaming instead). |
| R5 | Session-model unification — owner caught an inconsistency among the Run definition, REPL semantics, and `ask`; simplified to a single Session concept. |
| R6 | Two-part topology; tool boundary as authority membrane; web-reading tiers A/B/C. |

Each round followed AI-proposes → owner-decides → registry/artifacts-updated under append discipline. Full trail: `docs/ai-use-log.yaml`.

## 6. Context Engineering Design

*(Binding content per course D2.2: layered context structure, assembly pipeline, token-budget cap with compaction threshold, re-injection policy.)*

### 6.1 Layered context structure

| Layer | Content | Priority |
|---|---|---|
| L1 identity | Role definition, report output-format contract, language policy | never dropped |
| L2 standing constraints | Invariant reminders (INV-001/002/003 phrased as output rules), active glossary terms, tool catalog summary | never dropped |
| L3 retrieved knowledge | Current-turn tool results (values + provenance), sanitized news excerpts | high |
| L4 conversation history | Prior turns; **the only compactable layer** | medium |
| L5 resumable state | Session summary object: subject symbols, findings so far, open questions | survives via L5 |
| L6 current task | The user's current request | never dropped |

### 6.2 Assembly pipeline

`deduplicate (by data-record ID) → prioritize (by layer) → budget (by profile) → compact (L4 only, if triggered) → assemble → re-inject critical constraints`

Budget envelopes (configurable; per COST-001): quick ≤ 30k / standard ≤ 100k / deep ≤ 400k tokens per session. Allocation guidance: L1 + L2 fixed ≈ 2k tokens each; L3 ≤ 50%; L4 ≤ 30%; L5 ≈ 5%; ~10% output reserve.

### 6.3 Token-budget cap and compaction threshold

- **Threshold**: compaction triggers when assembled context reaches **80% of the profile budget** (default; user-configurable), or manually via `/compact`.
- **Mechanism**: oldest-first summarization of L4 turns into the L5 session summary, produced by the chat model under a strict summary schema. Summarized turns are replaced in the live context but never deleted from `session.jsonl` (audit trail intact, FR-011 append-only).

### 6.4 Re-injection policy after compaction

After every compaction, the assembler unconditionally re-injects, above the compacted history:

1. the invariant reminder block (L2);
2. the **provenance ledger** — a compact digest of every data record already used in the session (record IDs + value hashes);
3. the current subject symbol list;
4. the active task statement.

The provenance ledger is architecturally **non-compactable**: without it the INV-001 post-check loses its comparison basis in long sessions.

### 6.5 Model routing

Default for **all profiles and all model roles (chat, reasoning, event scoring, embedding): `deepseek-flash`**. *(Corrected 2026-09-17: the decision-time name `deepseek-v4.1-flash` does not exist in the live catalog — first live conversation returned HTTP 400 listing `deepseek-flash` / `deepseek-v4-pro`; recorded in AILOG-0023.)* Per-profile and per-role overrides are user-configurable (FR-021) — e.g., the owner may point the `deep` profile at a reasoning model with no code change.

*Implementation note*: the embedding endpoint of the configured provider is verified at implementation; if the endpoint family does not expose embeddings, configuration falls back to a separately configured OpenAI-compatible embedding provider (already supported by FR-021). No code change is implied.

## 7. Traceability

This ADR constrains: FR-011, FR-013, FR-019, FR-020, FR-021, INV-001, COST-001, GOV-005. It is referenced by the trace matrix for those requirements.

## Amendment 1 (2026-09-30, TP-019) — the L4 history window counts messages, and says when it cuts

§6.1 layer L4 (conversation history) was implemented as "the last 20
session events", and tool calls and tool results are events too: a
tool-using session kept about three turns of history, and the slice
could open with an assistant answer whose question had been cut off.
The fifth audit's live run showed the consequence - asked for "the
closing price you mentioned at the start", the model denied ever
having given one (turn 1 had fallen out of its context).

Correction: L4 is the last `HISTORY_WINDOW` (20) user/assistant
MESSAGES - about ten turns; tool events never consume it. The window
never opens on an assistant message (its question would be missing).
When older turns fall outside the window, a harness note tells the
model so ("say they are not in your context instead of guessing").
A quarantined answer is replayed to the model as a harness note
("withheld by the numeric post-check; the user saw only: data
unavailable for: ...") - read back verbatim, the degraded line made the
live model tell the user the data itself had been unavailable.
Compaction (§6.3) is unchanged; the full record stays in
`session.jsonl` (FR-011).

Implements: REQ-SI-FR-011, REQ-SI-COST-001.

## Amendment 2 (2026-10-04, TP-029) — an interrupted turn is left out of context

§6.1 layer L4 replayed every user and assistant message in its window,
including the question of a turn the user interrupted before its
answer (DE-14). On the next turn the model received that dangling
question again.

Correction: a turn that has a `turn-incomplete` event and no assistant
message is left out of L4 before the window is applied. It does not
replay, does not take a window slot, and does not trigger the
truncation note. A turn that has an answer is never left out, even if
a marker for it exists. Turns that end without an answer on other paths
(the iteration cap, a provider error) are unchanged by this amendment;
they are not interruptions.

Implements: REQ-SI-FR-011, REQ-SI-FR-023.
