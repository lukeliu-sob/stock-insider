# Debt Register — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/debt-register.md` (course deliverable D4) |
| Discipline | AI-era debt categories per course spec. Entries are appended; repayment closes an entry with a reference to the paying change set. A debt without a repayment trigger is unmanaged. |

## Category Overview

| Category | Open entries |
|---|---|
| Prompt rot | 0 |
| Hallucinated dependencies | 0 |
| Untouchable code | 0 |
| Hidden dependencies | 0 |
| Agent-induced bloat | 0 |
| Evaluation debt | 2 |
| Guardrail debt | 3 |
| Human/cognitive debt | 1 |

Categories at zero have no current entries; the category opens the moment its first entry appears — do not pre-register speculative debt.

## Entries

### DE-01 — Performance thresholds deferred
- **Category**: evaluation debt
- **Description**: PERF-001..003 hold `status: future` with TBD thresholds; no latency budgets anywhere in CI.
- **Repayment trigger**: real workloads exist (first working pipeline); set thresholds via requirement change, then move rows to active.
- **Status**: open (2026-09-15)

### DE-02 — Zero empirical evaluation evidence
- **Category**: evaluation debt
- **Description**: the evaluation logbook holds qualitative Q-entries only; no E-entry has ever run, so QA-001's 0.6 faithfulness threshold is unverified in practice.
- **Repayment trigger**: evaluation harness built (CI `eval` job guard removal); first E-entry recorded.
- **Status**: open (2026-09-15)

### DE-03 — Bash governance is heuristic
- **Category**: guardrail debt
- **Description**: guard G4 checks only unambiguous tokens (`.env`, `sessions/`) in bash commands; other runtime-state paths reachable via shell are governed by review only.
- **Repayment trigger**: a shell-side incident or a third missed pattern → extend `governance-gate.ts` deny-list or accept documented residual risk via ADR.
- **Status**: open (2026-09-15)

### DE-04 — pi role separation is behavioral
- **Category**: human/cognitive debt
- **Description**: plan/build/verify role discipline in pi relies on convention (AGENTS.md), not mechanics; only path rules are enforced by the governance gate.
- **Repayment trigger**: a role-discipline incident, or team growth beyond current size → build scoped role agents under `.pi/agents/` (option-ledger entry).
- **Status**: open (2026-09-15)

### DE-05 — CI existence guards
- **Category**: guardrail debt
- **Description**: `quality`, `regression`, and the eval harness check are existence-guarded (pass with a note) until `pyproject.toml`, offline tests, and `test/live/test_eval_set.py` land. Each guard removal is its own PR with its own test plan (verification-constraints §4).
- **Repayment trigger**: corresponding artifact lands.
- **Status**: open (2026-09-15)

### DE-06 — Cross-file reference validity unautomated
- **Category**: guardrail debt
- **Description**: references between artifacts (ADR ↔ AI-log ↔ registry ↔ blueprint baselines) are human-maintained; BD-4 showed the class of error. No `reference_lint.py` exists.
- **Repayment trigger**: second incident of this class, or reference count grows past ~30 → add a reference-lint structural script.
- **Status**: open (2026-09-15)
