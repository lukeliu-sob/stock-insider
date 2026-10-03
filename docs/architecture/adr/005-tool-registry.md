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


## Amendment 1 (2026-09-29) — Registry/facade boundary restored (review finding 2)

Ruling 1 above says the registry imports only `shared`, with tool
handlers injected by the composition layer. Eight merged PRs (#8 #9
#14 #19 #22 #30 #33 #39) drifted from that: handlers grew inline SQL
against the store connection and direct imports of data internals
(`data.ingest.fundamentals`, `data.compute.indicators`). The boundary
gate codified the drift instead of blocking it (registry -> any data
module was allowed). A third-party review caught both.

Restoration (PR-gamma, TP-016):

1. All storage SQL and data-internal imports moved behind the data
   facade: `market_quote`, `fundamentals_coverage`, `news_recent_rows`,
   `market_indicators_snapshot` are facade methods; registry handlers
   delegate. `market.indicators` computation lives entirely on the
   data side (which is also FR-006's arithmetic boundary).
2. `import_boundaries.py` tightened to the letter of this ADR:
   `agent/registry` may import exactly `stockinsider.data` (the facade
   package) — any deeper data module is a violation. Plain `agent`
   modules may import no data at all (unchanged).
3. A source-invariant test pins the restoration: registry.py contains
   no `stockinsider.data.` import and no `.conn` access (structural,
   so the drift cannot silently recur).

The capability story is unchanged: injection remains the mechanism;
the facade simply names the injection surface on the data side.

## Amendment 3 (2026-09-29, TP-018) — write-tool confirmation tokens: design and its non-relay principle

TP-017 PR-2 introduced one-time human confirmation tokens for
write-class tools (H3). The design as shipped had four defects found
by the third audit; this amendment records the corrected design (and
supersedes the interim "ADR-005 Am1" citations on the token code,
which were wrong: Am1 is about the facade boundary, not consent):

1. Non-relay principle. The confirmation token NEVER travels through
   model text. The engine intercepts a write-class call, issues the
   token via the ConfirmationBroker, and renders the pending write
   (tool + arguments + token) to the human directly through the
   progress() chrome channel — chrome is harness output, not model
   output, so INV-001 never post-checks it. The model's tool result
   says only that a human confirmation is pending and must not be
   repeated. Rationale: an 8-char hex token contains digits with
   probability ~99.96%; a relayed token was guaranteed to be
   quarantined by the numeric post-check ("data unavailable for:
   808, 808"), making the flow unusable and invisible.
2. Token alphabet: 8 lowercase letters (`secrets.choice`, 26^8
   space). Defense in depth — even a model that disobeys and repeats
   the token injects no extractable digits.
3. Bound-content visibility: the confirm echo and the pending-write
   render both show the exact (tool, arguments) the token unlocks.
4. History write-back: after the harness executes a confirmed write,
   it appends a `[harness] confirmed write executed: ...`
   user-message event. `_history_messages` reads user/assistant
   events only, so this is the minimal channel through which the
   model learns the outcome — without it, /report truthfully-claimed
   falsehoods about watchlist state that passed every check.
5. Expiry: `expire_turns` runs at the start of every run_turn
   (max_age 3 turns); tokens no longer linger indefinitely.
6. Input routing: the REPL consumes an input line as a confirmation
   only when it matches `confirm [a-z]{8}` exactly; anything else —
   including questions that merely start with "confirm" — is a
   normal conversational turn.

Amendment 2 (resolver honesty, same date): `resolver.record` marks a
candidate `verified=1` only when its exchange is in
PRIMARY_EXCHANGES (HK/US/INDX). Secondary-venue listings return as
folded `verified=0` candidates — the constant's original intent —
because a verified XETRA row is a verified path to adding an
out-of-scope listing (INV-004 requires verified resolution for
watchlist additions; scope is HK + US).

Implements (with ADR-006 Am5/Am6, ADR-004 Am2): REQ-SI-INV-004.

## Amendment 4 (2026-10-03, TP-025) — Declared result-field semantics (DE-15, DE-16)

§4's reopen condition ("nested schemas may trigger the jsonschema/pydantic
adoption") has fired, concretely: `agent/guardrail_claims.py`'s INV-001
typed-claim engine (ADR-008 Am1, TP-024) types a cited number's field by a
hand-maintained cue vocabulary (`_KEY_FIELDS`, `_METRIC_FIELDS`,
`_CUE_PATTERNS`) guessing at what a tool result's keys mean, because
`ToolSpec` carries no field-level semantics today — `result_spec` is only
a top-level type tag ("dict"/"list"); `validate_result_payload` never
looks inside. DE-15 (field/subject typing is heuristic) and DE-16
(company names resolve only when the ledger happens to carry one) are
this gap's two debt entries. ADR-008 §9's own "Change sets" row already
scopes this as its phase 3 (TP-025); one of its cross-references
(decision log, "tools declare the semantics of their result fields in
`shared/` (ADR-004 amendment)") names the wrong ADR — ADR-004 explicitly
deferred tool I/O schema design to this one (§4 Reopen Conditions: "Tool
I/O schema design (TP-005/ADR-005) may extend `shared/` with a
tool-envelope module"), which is exactly `shared/tools.py`. Corrected here
and at the citing line.

**Decision: a metadata declaration, not a schema-validation library.**
The reopen condition's named alternative (jsonschema/pydantic) buys
structural validation of result *shape*; what DE-15/DE-16 need is
*semantic* labels on fields whose shape is already fine. Adopting a
schema library now would add a dependency (AGENTS.md §8 stop-and-ask) to
solve a problem one level up from where it lives. Instead, `ToolSpec`
gains two optional fields that mirror the two shapes the existing
heuristic vocabulary already separately encodes - a direct key and a
discriminator-tagged key (`market.indicators`' `{metric, value}` rows,
where `value`'s meaning depends on its sibling `metric`):

```python
@dataclass(frozen=True)
class FieldSemantics:
    field: str              # canonical field name, e.g. "close", "volatility", "roe"
    unit: str = ""           # "" | "fraction" | "percent" | "currency" | "count"
    subject_bearing: bool = False  # this field's value is itself a subject identifier (e.g. official_name)

@dataclass(frozen=True)
class ToolSpec:
    ...
    result_fields: dict[str, FieldSemantics] = field(default_factory=dict)
    result_discriminators: dict[str, dict[str, FieldSemantics]] = field(default_factory=dict)
```

A tool declares `result_fields={"close": FieldSemantics("close", unit="currency"), ...}`
for direct keys, and `result_discriminators={"metric": {"volatility": FieldSemantics("volatility", unit="fraction"), ...}}`
for the metric/value pattern. Neither is validated by `Registry.execute()`
(§1 ruling 3's four-stage order is unchanged) - this is declared metadata
for `agent/guardrail_claims.py`'s evidence-typing to consume, not a new
registry enforcement point (Amendment 1's lesson: the registry's job
stays dispatch and the fail-closed wire checks, not creeping scope).
Consumption, the per-module migration (data/ingest/market.py, fundamentals.py,
indicators.py, news.py, eodnews.py, sync.py, watchlist.py, resolver.py,
and the `data/store/__init__.py` facade that assembles composite
payloads), the heuristic-fallback rule for anything not yet migrated, and
`official_name` reaching `market.quote`/`market.indicators`/
`fundamentals.summary`/`news.*` for DE-16, are TP-025's implementation
(this amendment records the wire-format decision; the guardrail-side
consumption is recorded as ADR-008's own phase 3 amendment once that code
lands).

**Alternatives considered:**
- Full jsonschema/pydantic adoption now (the reopen condition's own
  suggestion): rejected as oversized for a semantic-labeling problem;
  revisit if result *shapes* (not just field meaning) start needing
  structural validation.
- Leave the heuristic in `guardrail_claims.py` permanently: rejected -
  that is DE-15/DE-16 staying open by design, not a decision.
- Fix DE-15/DE-16 ad hoc, tool by tool, without a declared mechanism:
  rejected - the next new tool reintroduces the same gap.

**Residual risk**: a company absent from a session's ledger entirely
still cannot be recognized as a subject, even after `official_name`
flows everywhere a result carries one (DE-16's own trigger text already
names this). TP-025 closes the two named debt entries; this residual is
recorded there, not claimed closed.

Implements: REQ-SI-INV-001, REQ-SI-SEC-002 (with ADR-008's phase 3).
