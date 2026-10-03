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
| Guardrail debt | 5 (DE-03, DE-08, DE-11, DE-15, DE-16) |
| Human/cognitive debt | 1 |

Categories at zero have no current entries; the category opens the moment its first entry appears — do not pre-register speculative debt.

## Entries

### DE-01 — Performance thresholds deferred
- **Category**: evaluation debt
- **Description**: PERF-001..003 hold `status: future` with TBD thresholds; no latency budgets anywhere in CI.
- **Repayment trigger**: real workloads exist (first working pipeline); set thresholds via requirement change, then move rows to active.
- **Status**: open (2026-09-15). Partially instrumented by TP-026 (2026-10-03): `test_cli_info.py`, `test_ingest_market.py` and `test/live/test_eval_set.py` now print a `time.perf_counter()` duration for the operation each PERF row names, so the next several runs accumulate real numbers. No threshold is asserted and `status: future` is unchanged - the trigger (real workload data) still has not fired.

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
- **Status**: repaid by TP-026 (2026-10-03): `tools/checks/reference_lint.py` collects every DE-NN/TP-NNN/RM-NN/ADR-NNN/REQ-SI-\* token cited under `docs/` and fails on one with no matching entry in its home artifact, wired into the CI `structural` job. First real run found no genuine dangling reference, only pre-existing letter-suffix shorthand (TP-011a/b, TP-012a/b, TP-013a/b, TP-018b citing a plan filed only under its bare number, now accepted by matching on the shared 3-digit base) and one deliberate forward reference (TP-025, pinned by name, ADR-008's already-planned phase 3).

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
- **Status**: repaid. (c) decided 2026-10-02 (ADR-008): rounding to any written precision, whole numbers included, is an allowed rendering, implemented against typed candidates in phase 2 (TP-024); until then such numbers are flagged, no longer withheld. (a), (b) and (c) repaid by TP-024 (2026-10-02, ADR-008 Am1): counts verify against list lengths, symbol-shaped tickers are identifiers, rounding to the written precision is implemented for typed candidates. (d) repaid by TP-026 (2026-10-03): `prompts/identity.md` v7 adds "Tool-call arguments are not evidence" next to the existing citable-evidence rule; `test_model_citing_request_arguments_fails_postcheck` confirms the ledger-side defense (request arguments were never added to it) catches the citation even if the prompt rule were ignored.

### DE-11 — Watchlist entries on secondary venues from before migration v6
- **Category**: guardrail debt
- **Description**: migration v6 demoted pre-ADR-005-Am2 secondary-exchange rows to verified=0, but a symbol already ACTIVE on the watchlist stays active and keeps syncing; no report lists such entries.
- **Repayment trigger**: the first owner database found to hold one (a `watch list` warning or a one-off report), or the next INV-004 change set.
- **Status**: open (2026-09-30)

### DE-12 — INV-001 typed provenance is field-level, not symbol-level
- **Category**: guardrail debt
- **Description**: the M2 phase-1 typed pool checks WHICH FIELD a cited value belongs to (close vs open), not WHICH SYMBOL. In the TP-019 final-code live run the model put 0700.HK's close (644.63) into the 9988.HK column of a comparison table, then corrected the cell inline; the post-check passed because 644.63 is a real "close" in the ledger. A cross-symbol misattribution without a self-correction would reach the user unflagged.
- **Repayment trigger**: the M2 phase-2 test plan (ADR-006 Am7) → type pool values by (symbol, field) and check table columns/rows and sentence subjects against the symbol a value was returned for.
- **Status**: repaid by TP-024 (2026-10-02): evidence is typed by (subject, field class); table headers and sentence subjects are checked against the symbol a value was returned for.

### DE-13 — Partial-date residuals after TP-020
- **Category**: guardrail debt
- **Description**: TP-020 (ADR-006 Am9) checks month-years and framed bare years against the evidence calendar. Still quarantining: an unframed year ("2025 was volatile", a table cell "| Year | 2025 |"), "from 2025 to 2026" (from/to/between frame values as often as times), and a month inside an evidence window that is not the month of any evidence date ("October 2025" for a window 2025-09-25..2026-09-29 with no October date). Passing by design: a remembered year in a framed sentence ("in 2025 BYD overtook Tesla") whenever an evidence date falls in that year (owner-accepted, 2026-10-01), and a value equal to an evidence year in a temporal frame whose unit word is outside the value list.
- **Repayment trigger**: a live quarantine traced to one of these classes → extend the frame list together with its bypass test, or (owner decision) let a month inside a returned window count - that is range membership, not a registered value.
- **Status**: repaid by TP-024 (2026-10-02): sentence-subject years, time-word table labels and time-cued ranges are temporal; a month, quarter or year overlapping an evidence window verifies (owner decision P1). A bare year in a value position stays a numeric claim by design.

### DE-14 — Interrupted turns are not marked incomplete
- **Category**: session debt (documentation and code drift)
- **Description**: runtime policy P-17 and memory-design §3 specify that a turn interrupted before its post-check is written with status `incomplete` and excluded from context reconstruction (glossary: Incomplete Turn). The loop records nothing on interruption: the user message is already appended, no assistant message follows, and `_history_messages` replays the dangling question to the model on the next turn. Pre-existing; surfaced while planning TP-021, whose terminal UI makes Ctrl+C interruption routine.
- **Repayment trigger**: before the terminal UI becomes the default front-end, or on the first live report of a model answering an interrupted question.
- **Status**: open (2026-10-01; recorded by owner approval with TP-021)

### DE-15 — Phase-2 field and subject typing is heuristic
- **Category**: guardrail debt
- **Description**: field classes come from result key names and a cue vocabulary, and subjects from text proximity (TP-024 Appendix A). A misread cue flags a correct number. Keys outside the vocabulary stay compatible with any field, so a value under an unknown key can verify a fielded claim.
- **Repayment trigger**: TP-025 (ADR-008 phase 3), where tools declare result-field semantics in `shared/`; or a live false flag or escape traced to the vocabulary.
- **Status**: open (2026-10-02; recorded by owner approval with TP-024)

### DE-16 — Company names resolve only when the ledger carries them
- **Category**: guardrail debt
- **Description**:
  - Subjects resolve from three sources: tickers, bare codes, and the first word of an `official_name` in the ledger.
  - Market, indicator, news and fundamentals results carry no names. A misattribution written with company names ("Tencent's volatility of 37.1%", which is BYD's) is therefore checked against any subject, and can verify.
  - A company absent from the ledger entirely ("a 46.49% gross margin at BYD" in an Apple-only session) is not recognized as a subject at all.
  - Five held-out claims escape this way (E-010). The owner waived them for TP-024.
- **Repayment trigger**: TP-025 (ADR-008 phase 3). Tools return `official_name` with each subject-bearing result and declare field semantics in `shared/`. An unresolvable company name can then count as a subject without evidence.
- **Status**: open (2026-10-02; recorded by owner decision during TP-024)
