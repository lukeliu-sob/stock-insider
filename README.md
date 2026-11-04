# Stock Insider

A single-user, local, English-language **CLI financial analyst agent** for HK + US equities: daily EOD ingestion into local stores, deterministic computation, LLM analysis with full numeric provenance, and replayable sessions. It supports weekly personal investment research. **It analyzes; it never trades.**

This project is the CS5351 agentic software engineering course project, built AI-first under auditable human supervision: the requirements registry, architecture, and governance artifacts below were produced before any product code exists, and every AI-authored change is recorded in the AI-use log.

## Architecture in brief

Two parts separated by a **tool boundary** (the authority membrane):

- **Agent side** (`src/stockinsider/agent/`) — a self-built lightweight agent loop: REPL + slash commands, session persistence (append-only `session.jsonl`, values-as-seen context snapshots), layered context assembly with compaction and provenance-ledger re-injection, a deterministic guardrail (numeric post-check, epistemic filter, fail-safe), and user-configurable OpenAI-compatible providers (default `deepseek-flash`).
- **Data side** (`src/stockinsider/data/`) — an in-process package behind a facade: ingestion adapters (EODHD market data and fundamentals; EODHD, GDELT and ten curated RSS feeds for news, with whitelisted article-body backfill), SQLite + sqlite-vec storage, and deterministic indicators and trailing-window performance. The LLM reaches it only through schema-validated tools.

Four zero-tolerance invariants govern the product (`docs/architecture/invariants.md`): every number in output traces to the session's context snapshot; no deterministic causal claims or price predictions; failures are explicit, never substituted; watchlist additions only via verified symbol resolution.

## Repository layout

| Path | Content |
|---|---|
| `docs/req/` | D1 — requirements registry (`requirements.yaml`, 49 entries, v0.6.3), CI schema, glossary |
| `architecture-blueprint.md`, `docs/architecture/` | D2 — blueprint, ADRs 001–008 (with dated amendments), invariant register, trace matrix, memory/permission/policy/evaluation artifacts |
| `AGENTS.md`, `docs/code-governance/`, `.opencode/`, `.agent/`, `.pi/` | D3 — coding-agent governance (harness-neutral: opencode **and** pi; see `pi-adaptation.md`) |
| `docs/code-governance/verification-constraints.md`, `.github/workflows/ci.yml`, `tools/checks/` | D4/D7 — verification governance and the blocking-gate pipeline |
| `docs/review-memo.md`, `docs/debt-register.md`, `docs/bug-diary.md`, `docs/test-plans/`, `docs/ai-use-log.yaml` | Living QA and audit records |
| `Prompt.md` | D9 — static launch prompt for supervised coding-agent sessions |
| `transcripts/`, `Report.md` | D5/D6 — annotated student transcripts and the process report |
| `src/`, `test/` | D8 — application source and tests (offline default, live separated) |

## Running tests

```bash
# Offline suite (deterministic, fixtures + mocked providers) — the blocking default
python -m pytest test/offline

# Live suite (real provider calls) — never blocking; needs a provider key
PROVIDER_API_KEY=... python -m pytest test/live

# Full suite
python -m pytest test/offline test/live

# Structural tier (independent of pytest)
python tools/checks/registry_schema.py        # etc., see tools/checks/README.md
```

Implemented and tested end to end on a copy of a real store (2026-11-04): daily sync of market data and news (EODHD, GDELT, RSS), `embed` for the news vector index, watchlist with verified-symbol gating and confirmation, `info`, the analysis REPL (plain or `--ui tui`) with typed numeric post-checks and the epistemic filter (identity prompt v8), news retrieval (`news.recent`, `news.search`), indicators and `market.performance`, session list/show/resume, and the weekly `digest`. Not implemented: event scoring (REQ-SI-FR-009; the digest reports it as unavailable). Deferred by priority: Chinese news (FR-024) and quant models (FR-025). Accepted residuals are listed in `docs/debt-register.md` and `Report.md` §8.

## Running the application

```bash
python -m venv .venv && .venv/Scripts/pip install -e .   # Windows path; use .venv/bin on Unix
# keys go in a local .env (never committed): PROVIDER_API_KEY, EMBEDDING_API_KEY, EODHD_API_KEY
stockinsider watch add 0700.HK     # verified resolution + confirmation (INV-004)
stockinsider sync                  # daily EOD bars and news, under the call budget
stockinsider embed                 # embed new headlines for news.search
stockinsider info 0700.HK          # deterministic snapshot, no LLM
stockinsider analyze               # analysis REPL (add --ui tui for the terminal UI)
stockinsider digest                # weekly digest of the watchlist
stockinsider sessions              # list sessions; then `show` or `resume` one
```

## Blocking gates (CI design)

All six course gates are implemented in `.github/workflows/ci.yml` and `tools/checks/`:

| Gate | Mechanism |
|---|---|
| Test approval (D7-1) | Implementation PRs must reference an approved `docs/test-plans/TP-NNN.md`; `testplan_gate.py` validates |
| Static analysis (D7-2) | `structural` job: import boundaries, docstring traceability, language policy, secret scan, static arithmetic, tautology and reference lint; `quality` job: ruff and mypy |
| Schema (D7-3) | `registry_schema.py` validates the registry against `req-schema.json` |
| Semantic evaluation (D7-4) | `eval` job replays the evaluation set on prompt/model-routing changes (QA-001 thresholds block) |
| Regression (D7-5) | `regression` job runs the full offline suite; any old-test failure blocks |
| AI-use log (D7-6) | `aiuse_gate.py` blocks src/prompts changes without an AI-use-log diff |

Branch protection on `main` requires all six check contexts and enforces for admins, with linear history (owner decision 2026-09-16: approving reviews are a process discipline, not a mechanical block — the owner reviews every PR before merging; `CODEOWNERS` marks the requested reviewer). Safety-critical changes additionally require a linked ADR.

## Development with an AI coding agent

- Read `AGENTS.md` (the entry point) and launch sessions with `Prompt.md`.
- **opencode**: permissions in `.opencode/permissions.jsonc`; rules in `.opencode/rules.md`.
- **pi**: reads `AGENTS.md` natively; trust the project on first run so `.pi/extensions/governance-gate.ts` (the executable permission gate) activates. Mapping: `docs/code-governance/pi-adaptation.md`.
- Human-only files: `.opencode/rules.md`, `.agent/rules.md` — the agent reads them, humans write them.
