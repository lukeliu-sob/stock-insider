# Permission Model — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/architecture/permission-model.md` (course deliverable D2.6) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Related | `architecture-blueprint.md` §9; `.opencode/permissions.jsonc` (machine encoding, D3); `docs/code-governance/mcp-tool-manifest.md` |

**Scope**: file-level read/write rights for the AI coding agent's development-time roles (opencode). The runtime agent's permissions are defined separately in blueprint §9.1 — the two models are never conflated.

## 1. Principles

1. **Default deny**: no read, no write, for any path not listed below.
2. **Least privilege per role**: Plan reads; Build implements; Verify reads and runs.
3. **Human-only files**: some paths are authored exclusively by humans; the agent may read them as constraints, never write them.
4. **Safety-critical paths**: writable only with an ADR and explicit human approval (course blocking-gate rule), even where RW is otherwise granted.

## 2. Role–Path Matrix

| Path | Plan | Build | Verify | Notes |
|---|---|---|---|---|
| `src/`, `test/` | R | **RW** | R | Under structural constraints (D3). Safety-critical subpaths — `agent/guardrail*`, `agent/registry*`, `shared/` (egress whitelist, schemas) — require ADR + human approval per change. |
| `tools/` (verification scripts) | R | **RW** | R | CI infrastructure for the structural tier; changes accompany verification-governance edits. |
| `docs/req/`, `docs/architecture/` | R | **R** | R | Owner decision (R8, option a): the registry and architecture artifacts are the single source of truth; the coding agent reads them as constraints. Changes are owner-authored — the owner may paste agent-drafted content, with AI authorship recorded in the AI-use log. |
| `prompts/` | R | R | R | Changes flow only through the prompt-change process: ADR + evaluation-set gate + human approval (GOV-003). |
| `.github/workflows/` | R | R | R | CI gate integrity; human-approved changes only. |
| `AGENTS.md`, `Prompt.md` | R | R | R | Human-approved changes only. |
| `Report.md`, `transcripts/` | R | R | R | Human-authored deliverables. |
| `docs/code-governance/`, `docs/review-memo.md`, `docs/debt-register.md`, `docs/bug-diary.md`, `docs/ai-use-log.yaml` | R | R (log: append-only in same changeset as code/prompt changes) | R | Governance records; AI-use log updates accompany code/prompt changes per GOV-002. |
| `sessions/`, `data/` | **N** | **N** | **N** | Runtime state and privacy; the coding agent never touches them. |
| `.env`, local untracked config | **N** | **N** | **N** | Secrets (SEC-001). |
| `.opencode/rules.md`, `.agent/rules.md` | R | R | R | Human-only files. |

R = read · RW = read/write · N = no access.

## 3. Enforcement

1. `.opencode/permissions.jsonc` encodes this matrix mechanically (D3); the harness enforces it at tool-call time.
2. Branch protection backs it up: paths marked R for Build reject agent-authored commits without human review; safety-critical subpaths additionally require a linked ADR.
3. Review memos (D4) confirm permission compliance per pull request.
4. Violations are defects: they open bug-diary entries classified under guardrail debt.

## 4. Distinct Workflows on Record

- **Development-time (this document)**: opencode roles under the matrix above.
- **Owner-supervised artifact authoring (current practice)**: the owner directs an AI session to draft specification/architecture content; every write is owner-instructed and logged in `docs/ai-use-log.yaml`. This workflow is recorded for audit; it does not grant the coding agent standing write access to `docs/`.
