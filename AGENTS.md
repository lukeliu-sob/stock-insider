# AGENTS.md — Stock Insider

Entry point for any AI coding agent working on this repository. **Harness-neutral**: opencode and pi both load this file automatically. Read it before any task.

This file is deliberately compact. It **routes, it never duplicates**: a full sentence that appears both here and in another artifact is a review defect. Pointers and one-line summaries are the ceiling.

## 1. Mission and Build Target

Stock Insider is a single-user, local, English-language CLI financial analyst agent for HK + US equities: daily EOD ingestion into local stores, deterministic computation, LLM analysis with full provenance, replayable sessions. It analyzes; it never trades. Stack: Python 3.13+, typer + rich, SQLite + sqlite-vec, OpenAI-compatible providers (default `deepseek-flash`, per-role configurable).

Normative scope: the registry's `meta` three lists in `docs/req/requirements.yaml`. If a task conflicts with them, stop and ask (§8).

## 2. Non-negotiables

### 2a. Binding you — development rules

1. English only in code, comments, docs, commits, and every artifact you produce. (The product carries its own policy, REQ-SI-GOV-001 — you implement it in `src/`; this rule governs your dev output.)
2. Every change touching `src/` or `prompts/` updates `docs/ai-use-log.yaml` in the same change set.
3. The registry is append-only: new rows only; an old row's test failing is a regression — fix the code, never the test.
4. Obey the access map (§4) and the stop-and-ask list (§8).

### 2b. Binding the system you build — product invariants

The financial agent is governed by four zero-tolerance invariants. **They constrain the code you write, not your own behavior.** When a task touches an enforcement point (`guardrail`, `registry`, `shared/`, `data/ingest`), read the full entry in `docs/architecture/invariants.md` first.

- **INV-001** — every number in the product's output traces to the session's context snapshot; the post-check verdict is authoritative.
- **INV-002** — no deterministic causal claims or price predictions in the product's output; speculation carries a hypothesis label.
- **INV-003** — the product reports failures explicitly; never fabricates, never stale-as-fresh, never defaults.
- **INV-004** — watchlist additions only via verified symbol resolution + user confirmation.

Derived coding rules: no market-data arithmetic outside `data/compute`; fail-closed semantics everywhere in `data/ingest`; changes to `guardrail`/`registry`/`shared/` are gated (§4).

Full invariant fallbacks: `docs/architecture/invariants.md`.

## 3. Reading Protocol (load on demand — do not bulk-read)

Never read whole artifacts speculatively. The registry is grep-able: one entry per list item, so `grep "REQ-SI-FR-006" docs/req/requirements.yaml` returns exactly that entry.

| Task | Read (before starting) | Do not read |
|---|---|---|
| Any task | This file; `docs/req/glossary.md`; registry `meta` block | — |
| Plan a feature | `architecture-blueprint.md` §5 + §7; trace-matrix rows for affected REQs; the REQ entries themselves | ADR internals |
| Touch `agent/guardrail`, `agent/registry`, `shared/` | `docs/architecture/invariants.md`; ADR-001 §6 | ADR-002/003 |
| Ingestion / storage work | ADR-002, ADR-003; `docs/architecture/memory-design.md` | Context-engineering details |
| Documentation work | Registry discipline notes (file header); language policy (GOV-001 entry); relevant REQ entries | src structure constraints |
| Verification work | `docs/code-governance/verification-constraints.md`; target test suites | — |

Note: when a task touches a product-invariant enforcement point, you are *implementing* the product's constraints, not obeying them yourself — see the §2b framing.

## 4. Access Map

Default deny; full matrix in `docs/architecture/permission-model.md`. Quick table:

| Path | Plan | Build | Verify |
|---|---|---|---|
| `src/`, `test/` | R | RW | R |
| `tools/checks/` (verification scripts) | R | RW | R |
| `docs/`, `prompts/`, `.github/`, `AGENTS.md`, `Prompt.md`, `Report.md`, `transcripts/`, `.opencode/`, `.agent/`, `.pi/` | R | **R** (owner-authored changes only) | R |
| `sessions/`, `data/`, `.env` | **N** | **N** | **N** |

Safety-critical subpaths — `src/stockinsider/agent/guardrail*`, `src/stockinsider/agent/registry*`, `src/stockinsider/shared/` — are RW but every change requires a linked ADR and human approval. `prompts/` and `.github/workflows/` changes always require human approval.

## 5. Code Baseline and Module Map

Baseline discipline: **new work extends the existing baseline, never replaces it**. No module rewrites, no "cleaned-up" restructurings without an ADR.

```
src/stockinsider/
├── agent/   repl · session · context · guardrail · registry · providers   (advisory-side harness)
├── data/    ingest · store · compute · quant                              (authoritative side)
├── cli/     subcommand thin shell
└── shared/  glossary constants · provenance types · schemas · egress whitelist
```

Dependency direction (CI-enforced structural gate):

```
shared    → (nothing internal)
data/*    → shared only
agent/registry → data facade + shared          ← the ONLY agent→data channel
agent/*   → shared + agent/registry            (registry excluded from this rule)
cli       → agent facade + data facade
Forbidden: data→agent · agent(non-registry)→data · anything→cli
```

## 6. Integration Contracts

1. The data side is consumed **only** through its facade package; the LLM runtime reaches it **only** through `agent/registry` tools (schema in/out, provenance stamping, fail-closed).
2. All cross-module schemas and the provenance type enum live in `shared/`; no module defines its own wire format.
3. Sessions are append-only (`session.jsonl`, per-turn artifacts, per-response snapshots) — values-as-seen, never rewritten.
4. Every module and public function carries a docstring line `Implements: <REQ-ID> [, <REQ-ID>] (ADR-00N)` — enforced by `docs/code-governance/structural-constraints.md`.

## 7. Verification Requirements

Requirements the **generated code** must satisfy (verified by the checks below):

- Offline tests are the default gate: fixtures and mocked providers only (`test/offline/`). Live tests (`test/live/`) never block.
- Structural gates on every commit: import boundaries (§5), registry schema check, language check, static arithmetic gate (no market-data arithmetic outside `data/compute`) — scripts in `tools/checks/`.
- Per-change checklist: run affected `regression_scope` suites → run full prior suites (zero regressions) → update AI-use log → docstring references present.
- Every feature ships at least one negative/adversarial test (see `.agent/rules.md`).
- Every implementation PR references an approved test plan (`docs/test-plans/TP-NNN.md`, status: approved) — the approval gate blocks otherwise (REQ-SI-GOV-006).

## 8. Stop-and-Ask Protocol

Halt and request an owner decision before proceeding when the task would: modify the registry or any `docs/` artifact; change `prompts/`, CI workflows, or safety-critical paths; add a dependency or top-level module; touch an invariant's enforcement point; or conflict with the registry scope lists.

## Harness Notes

- **opencode**: permissions encoded in `.opencode/permissions.jsonc`; behavioral rules in `.opencode/rules.md` (human-only).
- **pi**: reads this file natively; the equivalent permission enforcement is `.pi/extensions/governance-gate.ts` (path blocking via `tool_call` interception). Mapping: `docs/code-governance/pi-adaptation.md`.
- Both harnesses share the same backstops: branch protection, review memos, CI gates.
