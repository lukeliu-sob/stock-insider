# Architecture Blueprint — Stock Insider

| Field | Value |
|---|---|
| Document | `architecture-blueprint.md` — master constraint document (course deliverable D2.1) |
| Version | 0.1.0 |
| Status | Draft — pending owner review |
| Date | 2026-09-15 |
| Registry baseline | `docs/req/requirements.yaml` v0.3.2 (47 entries) |
| Language policy | English only (`REQ-SI-GOV-001`) |

**Requirement reference convention**: requirement IDs appear in shorthand `FR-001` / `INV-002` / `QA-003` / `GOV-005` etc., all expanding to registry IDs `REQ-SI-<TYPE>-<NNN>` in `docs/req/requirements.yaml`.

This blueprint is the master constraint document of Stock Insider. It binds every downstream artifact: the coding agent reads it before planning any work (`AGENTS.md` declares the reading order), and no generated code may contradict it. Statements here are constraints, not suggestions; changing one requires an architecture decision record (ADR) and, for safety-critical sections, human approval (§12).

**Reading order** (restated from `AGENTS.md`): this blueprint → `docs/architecture/adr/` → `invariants.md` → `trace-matrix.md` → `memory-design.md` → `permission-model.md` → `runtime-policy-catalog.md` → `evaluation-table.md` → `docs/code-governance/` → `.opencode/rules.md` → `.agent/rules.md`.

---

## 1. Purpose and Audience

- **Purpose**: define the system's shape, boundaries, authority structure, and change discipline so that (a) an AI coding agent can extend the codebase only within governed limits, and (b) every human reviewer can locate, for any component, the requirements it implements and the invariants it enforces.
- **Audience**: the coding agent (hard constraint), the owner (decision record), and course reviewers (audit trail).
- **Position in artifact set**: first and outermost. All other D2 artifacts elaborate one section of this document; D3 (coding governance) and D4 (verification governance) operationalize it.

## 2. Scope

**System context**: a single-user, local, English-language CLI application. The owner uses it for weekly investment research on HK and US equities from daily EOD data. The system analyzes; it never trades, never serves multiple users, and never exposes a network service.

**Scope authority**: the requirement registry's `meta` three lists (must-do / must-not-do / out-of-scope) are the single source of scope. This blueprint does not duplicate them; any scope change happens there first, then propagates here via ADR.

**Deployment shape**: one Python package, one process per CLI invocation or REPL session. Embedded storage only (SQLite + vector store). No daemon, no service mesh, no container requirement.

## 3. Architectural Drivers

| # | Driver | Requirements | Consequence |
|---|---|---|---|
| D-1 | Verifiable anti-hallucination | INV-001..004, QA-004, FR-006, FR-008 | Every component must preserve the verifiability of LLM output: deterministic computation, provenance stamping, guardrail post-check, values-as-seen snapshots. This driver dominates all others when they conflict. |
| D-2 | Auditability and traceability | FR-011, FR-012, FR-022, FR-023, GOV-005 | Append-only session persistence; every turn reconstructible; provenance on every record. |
| D-3 | Single-user local deployment | registry meta; SEC-003 | Data side is an in-process package; embedded databases; egress limited to whitelisted endpoints. |
| D-4 | English-only stack | GOV-001, FR-014 | One language for docs, data, code strings, and output; sole exception: Chinese stock-name aliases in the symbol map. |
| D-5 | Tiered depth over cost minimization | FR-020, COST-001 | Profiles (`quick`/`standard`/`deep`) govern budget and routing; generous ceilings act as safety rails, not objectives. |
| D-6 | Dual (Type-C) governance | course classification; GOV-002/003 | Two supervised pipelines: the coding agent at development time and the runtime LLM at execution time, each with its own tool registry, permissions, and risk checklist. They are never conflated. |

## 4. System Boundaries

### 4.1 The Tool Boundary (authority membrane)

The single most important line in this architecture: **the LLM never touches storage, network, or computation directly.** All access flows through the tool registry (`agent/registry`), where every tool declares:

- an input JSON schema and an output JSON schema (both validated; malformed = fail closed, `REQ-SI-INV-003`);
- a provenance stamping rule for its outputs (`api` / `crawled` / `computed` / `model-judgment`);
- an effect class: `read`, `compute`, or `write` (write effects are gated — see §9.1);
- failure semantics: explicit error reports, never defaults or silent repair.

Initial tool catalog (each tool is a governed artifact; additions require a registry change and ADR):

| Tool | Effect | Backing module | Requirements |
|---|---|---|---|
| `get_quote` | read | `data/store` | FR-005, FR-001 |
| `get_fundamentals` | read | `data/store` | FR-005, FR-002 |
| `compute_indicators` | compute | `data/compute` | FR-006 |
| `search_news` | read | `data/store` + vector store | FR-007, QA-002 |
| `score_events` | write (model-judgment) | `agent/providers` + `data/store` | FR-009 |
| `event_study` | compute | `data/compute` | FR-010 |
| `watchlist_add` / `watchlist_remove` / `watchlist_list` | write (gated) | `data/store` | FR-004, INV-004, GOV-004 |
| `sync_status` | read | `data/ingest` | FR-001 |
| `fetch_url` | read (whitelist) | `data/ingest` (crawler) | FR-015 |
| `fx_rates` | read | `data/store` | FR-017 |

Deterministic read/compute tools are additionally user-invocable directly via `/tools` (§9.1) — a zero-LLM, zero-hallucination path.

### 4.2 External boundaries

- **Provider endpoints**: one chat endpoint and one embedding endpoint, user-configured, OpenAI-compatible (`FR-021`). Provider and model identifiers stamp every session record (`GOV-005`).
- **Data source endpoints**: market/fundamentals/news/FX APIs behind ingestion adapters; the commercial fundamentals vendor is chosen by candidate evaluation (ADR), not here.
- **Egress control**: a single HTTP-client choke point in `shared/` enforces the endpoint whitelist (`SEC-003`). No module may open sockets independently.

### 4.3 Explicitly excluded

Daemon/service mode; multi-user access; order execution or portfolio management; real-browser bridging (§9.4); social-media ingestion; intraday data. Each exclusion is mirrored in the registry's out-of-scope list or Won't entries.

### 4.4 Data-side interface contract

The data side is an in-process Python package (`data/`) exposing a facade API consumed exclusively by the tool registry and CLI. The facade is the seam along which a network service could later be extracted; MVP does not pay that cost.

## 5. Component Model

Module names equal architectural elements equal `src/` directories (course discipline: one architectural element ↔ one module).

```
src/stockinsider/
├── agent/        # advisory-side harness
│   ├── repl.py         # REPL loop, slash dispatch, streaming render
│   ├── session.py      # session lifecycle, persistence, resume
│   ├── context.py      # context assembly, compaction, re-injection
│   ├── guardrail.py    # post-check, epistemic filter, fail-safe
│   ├── registry.py     # tool registration, schema/permission gate
│   └── providers.py    # chat/embedding config, version stamping, usage
├── data/         # authoritative side
│   ├── ingest/         # source adapters, gap detection, backfill, filters
│   ├── store/          # SQLite schema, vector store, symbol map, watchlist
│   ├── compute/        # indicators, event study, statistics
│   └── quant/          # reserved boundary (REQ-SI-FR-025, deferred)
├── cli/          # subcommand thin shell
└── shared/       # glossary constants, provenance types, schemas, egress whitelist
```

| Module | Responsibility | Requirements | Authority |
|---|---|---|---|
| `agent/repl` | REPL loop, slash-command dispatch, streaming render, interactive follow-up after reports | FR-013, FR-014, FR-019 | advisory surface |
| `agent/session` | Session lifecycle (open → active → closed → resumed), persistence of `session.jsonl` / `artifacts/` / `context/`, sessions index | FR-011, FR-012, FR-023, GOV-005 | authoritative |
| `agent/context` | Layered context assembly, budgeting, compaction, critical-constraint re-injection | §8; FR-020, COST-001 | authoritative (deterministic) |
| `agent/guardrail` | Numeric post-check (values-as-seen comparison), epistemic filter, fail-safe enforcement | INV-001, INV-002, INV-003, QA-004 | authoritative — final verdict |
| `agent/registry` | Tool registration, schema validation, effect-class permission gate, provenance stamping | §4.1, §9.1; SEC-002 | authoritative |
| `agent/providers` | OpenAI-compatible endpoints, configuration, version stamping, usage accounting | FR-021, GOV-005, COST-002 | authoritative |
| `data/ingest` | Adapters (market, fundamentals, news, FX), schema validation, gap detection, backfill, relevance filter, dedup, retention | FR-001, FR-002, FR-003, FR-018, QA-003 | authoritative |
| `data/store` | SQLite + vector store schemas, symbol map, watchlist, provenance fields | FR-004, GOV-004 | authoritative |
| `data/compute` | Deterministic indicators, event study, retained-data statistics | FR-006, FR-010 | authoritative |
| `data/quant` | Reserved boundary for classical quant models | FR-025 | authoritative (deferred) |
| `cli` | Subcommand shell: sync, watch, info, analyze, resume, sessions, show, config, digest | FR-013 | — (thin shell) |
| `shared` | Glossary constants, provenance types, schemas, egress whitelist choke point | GOV-001, SEC-003 | authoritative |

## 6. Authority Boundaries

| Layer | Nature | Examples | Governing rule |
|---|---|---|---|
| LLM-generated content | **advisory** | report narration, event scores, follow-up answers | never displayed or stored without guardrail verdict; never executes anything |
| Tool outputs & computed results | **authoritative** | quotes, fundamentals, indicators, event-study numbers | schema-validated, provenance-stamped, values-as-seen recorded |
| Guardrail verdicts | **authoritative (final)** | post-check pass/fail, degradation decisions | outranks everything; a failed check cannot be appealed by model output |
| Event scores | **model-judgment provenance** | direction / strength / confidence / rationale | treated as data with provenance `model-judgment`, never as external fact |

**Three-layer defense** (`SEC-002`) placement:

1. **Input sanitization** — `agent/context` neutralizes instruction-like content in untrusted sources (news bodies, fetched pages) before they enter model context;
2. **Output validation** — `agent/registry` and `agent/guardrail` schema-validate every model output that touches analysis (e.g., event scores) and every tool output;
3. **Deterministic policy execution** — `agent/guardrail` and write-gated tools make final decisions; no layer is bypassable, and the failure mode of every layer is fail-closed (`INV-003`).

## 7. Agent Workflow

### 7.1 Session lifecycle

```
open ──► active ──► closed
            ▲          │
            └─ resume ──┘      (new turns appended; prior turns never rewritten)
```

States are recorded in the sessions index (`status`, `last_active_at`). Bare CLI invocation opens a new session; `resume` (default: most recent) reopens a closed one (`FR-023`).

### 7.2 Turn pipeline

```
user input
  ├─ slash command? ──► dispatch table (§7.3), no LLM
  └─ conversational turn:
        context assembly (§8)
        → provider call (streaming; reasoning stream rendered distinctly)
        → tool-call loop:
              registry validates schema → executes tool →
              stamps provenance → appends result to context snapshot
              (values-as-seen) → result re-enters context
        → response completes
        → guardrail post-check (INV-001 numeric verification vs. snapshot;
          INV-002 epistemic filter; fail → degrade per INV-003)
        → persist: session.jsonl append, snapshot write, usage accounting
        → render (degraded or full)
```

Every stage has an explicit failure path; none has a default value (INV-003).

### 7.3 Slash-command dispatch

| REPL command | CLI equivalent | Behavior | Requirement |
|---|---|---|---|
| `/resume [id]` | `resume` | resume closed session (default: most recent) | FR-023 |
| `/sessions` | `sessions` | list sessions, filterable | FR-012 |
| `/show [id]` | `show` | read-only session review | FR-022 |
| `/watch`, `/sync`, `/config` | `watch` / `sync` / `config` | data-side operations via facade | FR-004, FR-001, FR-021 |
| `/compact` | — | manual context compaction (§7.4) | §8; COST-001 |
| `/tools [name [args]]` | — | list registry; direct-invoke deterministic read/compute tools | §4.1, §9.1 |

Slash commands and CLI subcommands are two entries to one verb set; a third verb set is forbidden.

### 7.4 Compaction flow

`/compact` (or automatic threshold breach, §8) triggers: compress the conversation-history layer → rebuild context with **mandatory re-injection**: invariant reminders, current subject symbols, the active task statement, and the **provenance ledger** of data already used in the session. The provenance ledger is never compacted away — without it, the post-check loses its comparison basis and INV-001 would silently fail in long sessions.

## 8. Context Engineering (constraint summary)

Full design, alternatives, and rationale live in the ADR (course D2.2). Binding constraints:

1. **Layered structure** (highest priority first): identity/role → standing constraints (invariants, glossary terms) → retrieved knowledge (tool results, news) → conversation history → resumable state (session summaries) → current task.
2. **Assembly pipeline**: deduplicate → prioritize by layer → allocate budget by profile → compact → assemble → re-inject critical constraints.
3. **Budgets** (configurable defaults, `COST-001`): quick ≤ 30k, standard ≤ 100k, deep ≤ 400k tokens per session; overflow → compact-and-retry once per response → explicit budget-exceeded abort.
4. **Compaction threshold and re-injection policy**: history compacts first and deepest; standing constraints and the provenance ledger survive every compaction (§7.4).

## 9. Permissions

### 9.1 Runtime permissions

- Tools carry effect classes; `read`/`compute` tools are user-invocable via `/tools`; `write` tools (watchlist mutations, event-score storage) require either conversational flow with explicit user confirmation (FR-004/INV-004) or a CLI subcommand.
- Egress whitelist is enforced at the `shared/` HTTP choke point; no tool or module may bypass it.
- Local files: the agent writes only inside `sessions/` and the databases; every other path is read-only to the runtime agent.

### 9.2 Development-time permissions

File-level read/write rights for the coding agent are defined in `docs/architecture/permission-model.md` and encoded in `.opencode/permissions.jsonc`. Default: no read, no write; every path explicitly whitelisted.

### 9.3 Two registries, never conflated

- **Runtime tool registry** (this document, §4.1): what the Stock Insider agent may call at execution time.
- **Coding-agent MCP tool manifest** (`docs/code-governance/mcp-tool-manifest.md`, D3): what opencode may call during development.

The trace matrix references them separately; a PR that confuses them fails structural review.

### 9.4 Web-reading tiers

| Tier | Form | Priority | Rationale |
|---|---|---|---|
| A | static HTTP fetch + per-domain extraction templates (`FR-015`) | Should | covers most financial-media pages; bounded injection surface |
| B | headless-browser rendering | Could | only for JS-rendered sources; heavy dependency, gated by ADR |
| C | real-browser bridge driving the user's login sessions | **Won't** | conflates agent actions with user identity, violates the egress-whitelist model (`SEC-003`), and is indefensible under supervised-agent audit |

## 10. Verification Strategy

Three tiers (detailed rules in `docs/code-governance/verification-constraints.md`, D4):

1. **Structural** — import boundaries (agent must not import data internals except via facade), registry schema checks, static arithmetic gate (no market-data arithmetic outside `data/compute`, FR-006), language-policy check (GOV-001/FR-014), egress-whitelist check.
2. **Regression** — every registry entry's `regression_scope` suites; append-only discipline on the registry; old-row failure = fix code, never tests.
3. **Behavioral** — fixed evaluation-set replay (faithfulness ≥ 0.6, QA-001); adversarial suites for all four invariants with zero-escape criteria; boundary ±1 cases for threshold rules.

Test layout separates `test/offline/` (fixtures, mocked providers/resolvers — the default gate) from `test/live/` (real provider and data-source calls — never blocking).

## 11. Observability

Five recorded streams, each with a named consumer:

| Stream | Produced by | Consumed by |
|---|---|---|
| Session records (transcript, snapshots, artifacts) | `agent/session` | `show`, owner review, course audit |
| Tool-call log (args, latency, errors) | `agent/registry` | bug diary, debt register, runtime policy triggers |
| Post-check verdicts | `agent/guardrail` | QA-004 aggregation, INV-001/002 audit |
| Usage accounting (tokens per provider call) | `agent/providers` | COST-002 queries, budget overflow handling |
| Sync/gap reports | `data/ingest` | QA-003 completeness, INV-003 failure visibility |

## 12. Change Policy

- Architecture changes require an ADR: drivers → alternatives → decision → consequences → reopen conditions.
- Safety-critical changes (guardrail, registry permissions, egress whitelist, invariant enforcement points, prompt versioning) additionally require explicit human approval before merge (course blocking-gate rule).
- Registry co-evolution: every change answers the five questions (what changed in the spec; which upstream/downstream artifacts are affected; are review gates intact; are new regression tests needed; are all documents synchronized) before merge.
- This blueprint is versioned; a change to any §3–§9 constraint bumps the version and references the ADR.

## 13. Traceability

Every component in §5 declares the requirements it implements; every Must requirement in the registry maps to at least one component. The full requirement ↔ component ↔ test ↔ monitor mapping is maintained in `docs/architecture/trace-matrix.md`. A requirement without a component is an unkept promise; a component without a requirement is deletion debt.

---

*End of blueprint. Next artifacts in order: ADR (including full context-engineering design and the candidate evaluation that selects the commercial data vendor and the vector store), then invariants register, trace matrix, memory/state design, permission model, runtime policy catalog, evaluation table, risk list, and option ledger.*
