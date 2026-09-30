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
| Evaluation debt | 2 (DE-01, DE-09) |
| Guardrail debt | 5 |
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
- **Status**: repaid by TP-003 (2026-09-16): evaluation harness built and exercised; first E-entry (E-001, 6/6 = 1.00 ≥ 0.6) recorded from CI run 35054084367.

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
- **Status**: repaid. Quality and regression guards removed by TP-001 (2026-09-15); eval-harness guard removed by TP-003 (2026-09-16) with `test/live/test_eval_set.py` landing in the same change set. No existence guards remain.

### DE-06 — Cross-file reference validity unautomated
- **Category**: guardrail debt
- **Description**: references between artifacts (ADR ↔ AI-log ↔ registry ↔ blueprint baselines) are human-maintained; BD-4 showed the class of error. No `reference_lint.py` exists.
- **Repayment trigger**: second incident of this class, or reference count grows past ~30 → add a reference-lint structural script.
- **Status**: open (2026-09-15)

## DE-07 — Provider dotenv reader duplicates shared/envfile
- **Opened**: 2026-09-18 (BD-009 fix round)
- **What**: `agent/providers.resolve_api_key` carries its own dotenv parsing; the shared helper (`shared/envfile.py`, born this round) now owns that concern for the data side.
- **Why not now**: providers' path is green and test-pinned; migrating it is mechanical but touches 20+ config tests — deferred to a calm round (TP-009 config touchpoint is a natural moment).
- **Risk**: semantic drift between the two readers (currently identical: real env wins, STOCKINSIDER_ENV_FILE override, cwd default).
- **Exit**: providers imports shared/envfile; duplicate parsing removed; parity tests unchanged.
- **Closed**: 2026-09-18 — owner chose immediate repayment over deferring to TP-009. The provider env-file path helper now delegates to the shared one; the key resolver reads via the shared reader; the in-module parser is deleted. Parity tests unchanged and green (real env wins / file used / other lines preserved / missing key unset). Paying change set: DE-07 repayment PR (TP-003 Amendment 2).

### DE-08 — Sync counters are per run, not per day
- **Category**: guardrail debt
- **Description**: a gap's empty-attempt counter and the gap-repair budget share (half the daily cap) count per `sync` run. Three quick re-runs during a vendor outage can close a fillable gap as `no-data`; same-day repeated runs can spend more than half the day's calls on gap repair (fifth review; TP-019 kept the behavior, which existing tests pin, and made closed no-data gaps visible in `sync status`).
- **Repayment trigger**: a no-data closure observed for a range the vendor later serves, or a starved incremental in a same-day re-run → count attempts per calendar day and keep the share in the budget track.
- **Status**: open (2026-09-30)

### DE-09 — INV-002 regex recall is bounded; the fifth-audit sentences are now a development set
- **Category**: evaluation debt
- **Description**: the epistemic filter is a pattern set. TP-019 tuned patterns against the fifth review's held-out sentences, so E-008's numbers are development-set numbers, not independent held-out ones. Known open classes: a hedge that governs a different verb in the same clause ("We could see that the price will rise"), a fabricated attribution tag, paraphrases no pattern anticipates.
- **Repayment trigger**: the next review or evaluation round → measure on a freshly authored held-out set (author separated from the pattern writer); consider a second-stage classifier if recall stays below target.
- **Status**: open (2026-09-30)

### DE-10 — INV-001 strictness classes awaiting an owner decision
- **Category**: guardrail debt
- **Description**: counts and tickers absent from the evidence ledger ("Your watchlist now holds 3 symbols", "No data is stored for 9988.HK yet"), integer-rounded percents ("about 8%" for 0.0809) and the model's own tool-call arguments ("k=10 requested, 4 returned") quarantine whole answers by design (TP-017 PR-3a standing decision; BD-012/BD-015 match semantics; arguments stay outside the ledger because a fabricated argument would otherwise become citable). The live runs keep hitting these classes.
- **Repayment trigger**: owner decision on (a) list-length counts entering the ledger, (b) ticker tokens as structural references regardless of the ledger, (c) whether "about N%" is an allowed display form, (d) an identity-prompt rule against citing request parameters (prompts/ change, owner approval).
- **Status**: open (2026-09-30)

### DE-11 — Watchlist entries on secondary venues from before migration v6
- **Category**: guardrail debt
- **Description**: migration v6 demoted pre-ADR-005-Am2 secondary-exchange rows to verified=0, but a symbol already ACTIVE on the watchlist stays active and keeps syncing; no report lists such entries.
- **Repayment trigger**: the first owner database found to hold one (a `watch list` warning or a one-off report), or the next INV-004 change set.
- **Status**: open (2026-09-30)
