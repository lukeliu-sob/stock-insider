# ADR-005 — Tool Registry: The Authority Membrane

| Field | Value |
|---|---|
| ADR | 005 |
| Date | 2026-09-16 |
| Status | accepted (owner-approved with TP-005) |
| Related | blueprint §4.1 (tool boundary), §9.1 (runtime permissions), §7.3 (/tools); ADR-004 (shared charter); INV-001/INV-003; SEC-002; GOV/decision D-6 (dual registries) |
| Change set | TP-005 (`docs/test-plans/TP-005.md`) |

## 1. Decision

`agent/registry.py` implements the authority membrane: **the LLM never touches storage, network, or computation directly** — every access flows through registered tools. Five rulings:

1. **Injection-based registry (dependency-law preservation).** The registry imports only `shared`; tool handlers are callables injected by the composition layer (REPL/CLI today, the agent loop in TP-007; data-facade closures when the data side lands). This keeps the mandated edge set (`agent/registry -> shared + data facade`) literally true while allowing tools over any module the composition layer can see.
2. **Wire format authority in `shared/tools.py`** (per ADR-004's reopen condition, G2 protocol): `ToolSpec` (schemas + effect class + source kind), `ToolCall`, `ToolResult`, and fail-closed validators for both directions. Hand-written validators per ADR-004's pydantic deferral; the deferral's reopen condition now has a concrete trigger (nested result schemas when data tools arrive).
3. **Four-stage fail-closed execution** (INV-003): unknown tool → write-gate → argument validation → handler execution (exceptions become ok=False with the exception summary — never partial results, never swallowed) → result validation. The membrane is bidirectional: outputs that break their declared spec are rejected too.
4. **Effect-class gate (§9.1).** Every tool declares read/compute/write; `Registry.execute` refuses write-class calls unless the caller carries `allow_write=True`. The `/tools` user channel never sets it — write tools require the conversational confirmation flow (FR-004/INV-004) or a CLI subcommand.
5. **Provenance triple on success** (INV-001 groundwork): {tool, source_kind, produced_at}, where source_kind ∈ {api, crawled, computed, model-judgment} per blueprint §4.1. The guardrail's post-check (TP-006) and the context ledger consume these stamps.

**Ruling on `session.list`'s stamp class**: it uses `api` (the blueprint's four classes are closed); "from the local authoritative store" is carried in the tool description, not a new enum member. Extending the enum requires an ADR amendment.

**First registered tool set** (deterministic, zero external dependency): `budget.query` (compute/computed), `session.list` (read/api), `context.estimate` (compute/computed). `/tools` becomes real per blueprint §7.3 — listing and direct invocation go through the same membrane the agent loop will use; the REPL is a first-class membrane client, not a bypass.

## 2. Alternatives Considered

- **Direct function exposure to the LLM loop** (no membrane): rejected — this is the architecture's most important line; the whole governance story collapses without it.
- **Registry imports data/session modules directly**: rejected — breaks the mandated dependency edge; injection achieves the same capability without the violation.
- **External MCP-style tool server at development time**: rejected — conflates the two pipelines D-6 separates. The coding agent's tool governance (AGENTS.md/mcp-tool-manifest) and the runtime LLM's registry are distinct membranes; this ADR governs the runtime one only.
- **Full JSON-Schema (jsonschema library) validation now**: deferred — hand-written validators cover the current flat specs; adopt jsonschema when data-tool schemas go nested (same trigger as pydantic).

## 3. Consequences

- Every future tool lands as spec + handler + adversarial tests against the fail-closed matrix (unknown/schema/exception/gate); `test_inv3_failsafe.py` is the growing home for that matrix.
- Handler signatures are `dict -> Any` with top-level type checking only this round; deeper result validation is the data-tools TP's business.
- REPL string arguments mean numeric tool parameters pass as strings until the agent loop's native tool-calling arrives (which sends typed JSON); the current tool set is unaffected.
- The write gate is trusted-flag-based now; its enforcement against INV-004 (verified symbol resolution + user confirmation) lands with the watchlist TP.

## 4. Reopen Conditions

- Data-facade tools arrive (first data-side TP): register through the same membrane; nested schemas may trigger the jsonschema/pydantic adoption.
- Watchlist write flow (FR-004/INV-004): the confirmation protocol replaces the trusted flag.
- Agent-loop integration (TP-007): model tool-calling maps onto ToolCall envelopes; timing/parallelism decisions recorded there.
- A new source kind becomes necessary → ADR amendment (the four-class set is closed by design).
