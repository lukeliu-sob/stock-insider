# Review Memo — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/review-memo.md` (course deliverable D4) |
| Discipline | One entry per pull request, appended below. Entries are never edited after verdict except to add a follow-up note. |

## Verdict rules

- **APPROVE** — all sections check out; merge.
- **CHANGES REQUIRED** — concrete deficiencies listed; re-review after fixes.
- **REJECT** — spec or architecture misalignment that cannot be fixed within the PR (wrong requirement understanding, boundary violation, invariant erosion); the task returns to planning.

Security and efficiency are checked **throughout** every section, not as an afterthought. Permission compliance includes harness parity: if `.opencode/` or `.pi/` governance changed, `pi-adaptation.md` must be in the same change set.

## Entry template

```
## RM-NNN — PR #<number>: <title>

Date / reviewer / author (human or AI-drafted, human-approved):

Spec alignment:
  - Requirements touched (IDs):
  - Test plan referenced (TP-NNN, approved):
  - Fit criteria satisfied (evidence):

Architecture alignment:
  - Modules touched (must equal requirement's trace-matrix components):
  - Dependency direction respected:
  - ADR linked (mandatory for safety-critical paths):

Code quality:
  - Docstring traceability (Implements: lines):
  - Complexity / duplication / naming:

Test quality:
  - Negative/adversarial tests present:
  - Boundary ±1 cases (threshold rules):
  - Full prior suites green (zero regressions):

Operational metadata:
  - Runtime impact (if agent/ touched): token budget, policy paths affected
  - Performance/cost observations:

Security & efficiency (throughout):
  - Injection surface / sanitization:
  - Egress and secrets:
  - Resource efficiency:

Governance:
  - AI-use log updated in change set:
  - Permission matrix compliance (incl. harness parity):

Verdict: APPROVE | CHANGES REQUIRED | REJECT
Conditions / follow-ups:
```

## Entries

*(none yet — the first entry is created with the first implementation PR)*


## Backfill (2026-09-29) — retrospective entries for PRs #1-#48

Preamble: these entries were drafted retrospectively during the
third-party-review remediation round (TP-016 PR-epsilon) and
approved by the owner in that round. Safety-critical changes
(guardrail, registry, shared, prompts, CI) carry the full
template compressed; the rest carry one-line verdicts. From PR #49
onward, entries are written before merge (enforced by the
test-plan gate's safety-path attestation).

### RM-5 — PR #5: TP-004 shared foundation

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-GOV-001/002, SEC-001..003; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-004; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-6 — PR #6: TP-005 tool registry membrane

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-003, GOV-004; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-005; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-7 — PR #7: TP-006 runtime guardrail

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-INV-001, INV-002, QA-004; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-006; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-8 — PR #8: TP-007a agent loop core

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-008/019, COST-002; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-001; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-9 — PR #9: TP-007b session review/resume

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-022/023; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-001; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-14 — PR #14: TP-008 data store skeleton

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-004, INV-004; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-003; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-15 — PR #15: BD-009 resolver live wiring

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-004; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-002; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-17 — PR #17: BD-010 egress host fix

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-SEC-003; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-004 Am; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-19 — PR #19: TP-009 market ingestion

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-001, QA-003; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-002; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-22 — PR #22: TP-010 fundamentals + compute birth

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-002/005; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-002/003; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-23 — PR #23: BD-012 display-rounding allowance

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-INV-001; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-006 Am1; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-25 — PR #25: TP-011a news filter core

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-006; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-002; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-26 — PR #26: TP-011b GDELT transport + storage

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-006; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-002/003; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-29 — PR #29: TP-012a sanitizer + vector store

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-SEC-002, FR-007; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-004 Am1; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-30 — PR #30: TP-012b news.search tool

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-007; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-005; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-33 — PR #33: TP-013a indicator suite

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-006; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-002; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-35 — PR #35: TP-013b /report gate

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-008; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-006; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-38 — PR #38: TP-014 EODHD news primary

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-006; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-002/003; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-39 — PR #39: news.recent retrieval member

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-FR-007; test plan referenced and approved at merge time.
- Architecture: ADR linked: TP-012 Am1; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-44 — PR #44: BD-019 snapshot per-call keys

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: REQ-SI-INV-001; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-006; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-45 — PR #45: TP-016 PR-alpha remediation

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: review findings 5,7,8,9,11; test plan referenced and approved at merge time.
- Architecture: ADR linked: TP-016; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-46 — PR #46: TP-016 PR-beta coverage+exemption

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: review findings 4,10; test plan referenced and approved at merge time.
- Architecture: ADR linked: TP-016; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-47 — PR #47: TP-016 PR-gamma registry boundary

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: review finding 2; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-005 Am1; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

### RM-48 — PR #48: TP-016 PR-delta arithmetic gate

- Verdict: APPROVE (retrospective; owner-approved remediation round 2026-09-29).
- Spec alignment: review finding 3, FR-006; test plan referenced and approved at merge time.
- Architecture: ADR linked: ADR-002; dependency direction respected (import-boundaries gate green at merge).
- Test quality: negative/adversarial cases present per the registry discipline; full prior suites green (zero-regression rule enforced by CI).
- Security/efficiency: checked throughout (egress whitelist, secret scan, budget accounting where applicable).

- RM-1 — PR #1: TP-001 scaffolding; approved; first offline tests.
- RM-2 — PR #2: Governance record completion; approved.
- RM-3 — PR #3: TP-002 runtime skeleton; approved.
- RM-4 — PR #4: TP-003 providers/config/eval harness; approved.
- RM-10 — PR #10: BD-010 model-name fix; approved.
- RM-11 — PR #11: BD-007 resume close-before-bind; approved.
- RM-12 — PR #12: Resume picker; approved.
- RM-13 — PR #13: TP-008 docs; approved.
- RM-16 — PR #16: DE-07 env parser consolidation; approved.
- RM-18 — PR #18: TP-009 docs; approved.
- RM-20 — PR #20: BD-011 .INDX suffix; approved.
- RM-21 — PR #21: TP-010 docs; approved.
- RM-24 — PR #24: TP-011 docs; approved.
- RM-27 — PR #27: BD-013 transport-seam throttle; approved; seam-level test lesson.
- RM-28 — PR #28: TP-012 docs; approved.
- RM-31 — PR #31: BD-014 report as_dict news field; approved.
- RM-32 — PR #32: TP-013 docs; approved.
- RM-34 — PR #34: BD-015 marker-gated percents; ADR-006 Am2; approved.
- RM-36 — PR #36: BD-016 enumeration markers; ADR-006 Am3; approved.
- RM-37 — PR #37: TP-014 docs; approved.
- RM-40 — PR #40: BD-018 ISO date folding; ADR-006 Am4; approved.
- RM-41 — PR #41: TP-015 PR-a CLI polish; approved.
- RM-42 — PR #42: TP-015 PR-b watch governance + BD-017; approved.
- RM-43 — PR #43: TP-015 PR-c errors + sessions; approved.

### RM-53 — PR #53: final package (M9/M10/N2, registry_version, CI lock, INV-002 P/R, battery set)

- Verdict: APPROVE (pre-merge entry; owner-approved remediation round).
- Spec alignment: REQ-SI-SEC-003 (M9 egress on model runtime), REQ-SI-GOV-004 (M10 cap on reactivation), REQ-SI-GOV-006 (N2 memo-in-diff), registry discipline (version 0.4), QA-001 (INV-002 P/R + battery set, E-007).
- Architecture: providers gain the same whitelist hop as data fetching; the CI regression job installs from uv.lock (the lock is load-bearing).
- Test quality: cap-bypass negative, egress-rejection negative, memo-in-diff negative, INV-002 10/10 labeled suite; full prior suites green.
- Security: model-runtime egress now whitelist-gated (the last uncovered outbound hop).

### RM-51 — PR #51: write tools take human confirmation tokens (H3) — BACKFILLED

- Verdict: APPROVE (backfilled 2026-09-29 by owner-authorized TP-018; the PR body claimed
  "Review-Memo: appended" but no entry rode the diff — the third audit caught the forgery).
- Spec alignment: REQ-SI-INV-004, REQ-SI-FR-004 (user_confirmed boolean removed from every
  write tool spec; single-use ConfirmationBroker introduced).
- Architecture: conversational path never sets allow_write; write calls intercepted with a
  one-time token; consumed-token replay is the only executing path.
- Test quality: token single-use negative, unknown-token negative, replay positive.
- Security: model-filled consent booleans eliminated at the tool boundary.
- Residuals found by the third audit and fixed in TP-018 PR-1 (ADR-005 Am3): digit-bearing
  tokens were quarantined when relayed (flow unusable), confirmations were invisible to the
  model history, tokens never expired, "confirm"-prefixed questions were swallowed.

### RM-52 — PR #52: numbers pipeline (cross-turn ledger, structural tokens, M7/M8/M11, N1) — BACKFILLED

- Verdict: APPROVE (backfilled 2026-09-29 by owner-authorized TP-018; same forgery class as
  RM-51 — the branch commit message said "RM-52 appended" but docs/review-memo.md was not in
  the diff).
- Spec alignment: REQ-SI-INV-001 (session ledger, structural symbol fragments), REQ-SI-FR-005
  (M7 adjusted prices in indicators), REQ-SI-FR-002 (M8 honesty record), REQ-SI-FR-007 (M11
  news k clamp).
- Architecture: snapshot keys per successful call (BD-019); symbol-shaped fragments become
  structural tokens; indicators price the COALESCE(adjusted_close, close) series.
- Test quality: same-tool eviction negative, symbol-fragment positive, k-clamp negatives.
- Security: none beyond INV-001 semantics.
- Residuals found by the third audit and fixed in TP-018 (ADR-006 Am5/Am6): ledger keys were
  turn-colliding (a later turn's market.quote#1 evicted an earlier turn's), the regeneration
  recheck used the turn snapshot instead of the session ledger, and info.py day-move/vs-20
  lines still priced raw closes.

### RM-54 — TP-018: third-audit remediation (token flow, prelude validation, gates, honesty)

- Verdict: APPROVE (owner authorized the full plan in session 2026-09-29 after the third
  review; executed as one change set with ADR amendments attached).
- Spec alignment: REQ-SI-INV-001 (prelude validated + session ledger with turn-scoped keys +
  OHLCV typed provenance phase 1), REQ-SI-INV-002 (reported-speech exemption, modal classes,
  author-separated battery), REQ-SI-INV-003 (zero-bar gaps stay open; malformed tool
  arguments fail explicitly; event schema enforced at append; fundamentals.summary honest
  shape), REQ-SI-INV-004 (non-relay letter tokens, bound-content display, history write-back,
  expiry, strict routing, primary-exchange-only verification), REQ-SI-SEC-003 (no-bare-
  EgressViolationError, write-time config validation, EGRESS_EXTRA_HOSTS), REQ-SI-GOV-006
  (memo gate runs before the no-implementation early return and requires a real RM heading),
  REQ-SI-FR-014 (Latin allowlist), REQ-SI-FR-023 (aborted sessions terminal).
- Architecture: ADR-004 Am2, ADR-005 Am2/Am3, ADR-006 Am5/Am6; invariants.md INV-001 wording
  updated to the session-ledger semantics; ci.yml --frozen -> --locked.
- Test quality: 26 new adversarial tests (test/offline/test_tp018_remediation.py) including
  token-relay non-leak, confirm-question routing, fabricated prelude, aborted-resume refusal,
  blank-line memo, three-digit heading ordinal, zero-bar gap, Cyrillic/Hangul/Greek,
  open-quoted-as-close, doji pass; full suite 406 green; ruff + mypy clean; all structural
  gates pass.
- Security: the egress policy surface is unchanged in scope but now fail-closed at config
  write time and crash-free at runtime; extension hosts require an explicit owner env entry.


### RM-55 — TP-018b: fourth-audit remediation (sync starvation, guardrail regressions, gates)

- Verdict: APPROVE (owner authorized the full plan and PR submission, 2026-09-29).
- Spec alignment: REQ-SI-FR-001 (budget share + listing-clip + honest no-data terminal
  state), REQ-SI-INV-001 (snake_case fields, identifier codes, heading ordinals,
  deferred regeneration replay), REQ-SI-INV-002 (narrowed attribution, expected-to
  class), REQ-SI-INV-003 (empty PR body fails the gate; deferrals explicit),
  REQ-SI-INV-004 (identity v6 non-relay wording; migration v6 demotes stale verified
  rows), REQ-SI-FR-014 (widened closed allowlist), REQ-SI-SEC-003 (loopback HTTP
  exception), REQ-SI-FR-006 (N1 gate: .get/variable-key/alias detection).
- Architecture: ADR-004 Am3, ADR-006 Am7, schema migration v6.
- Test quality: 18 new adversarial tests (test_tp018b_fourth_audit.py) - quota
  simulation, clip-to-listing, migration demotion, laundering sentences, table
  prose, deferred replay (fabricated regen never reaches the screen), empty-body
  gate, loopback; full suite 424 green; ruff/mypy clean.
- Security: loopback HTTP is scoped to 127/8 + localhost + ::1 only; remote HTTP
  still refused.


### RM-56 — TP-019: fifth-audit remediation (INV-001/SEC-003 bypasses, regeneration, history, sync honesty)

- Verdict: APPROVE pending owner merge (owner authorized the remediation and its
  records in session, 2026-09-30; TP-019 committed before any implementation change).
- Spec alignment: REQ-SI-INV-001 (closed identifier set - letter-glued numerics are
  checked again; natural-date folding; "vol" alias removed), REQ-SI-INV-002
  (speech-act attribution with an adjacent institutional source; clause-local hedges;
  lower-case modal "may"; recall batch; the regeneration request replays the
  conversation; every regeneration/refusal recorded), REQ-SI-SEC-003 (loopback is an
  address, not a hostname prefix), REQ-SI-FR-001 (benchmark indices refresh daily;
  detection bounded by the cursor), REQ-SI-INV-003 (empty market answers fail with
  the cursor unchanged; closed no-data gaps visible), REQ-SI-FR-011 (history window
  counts messages, never opens mid-turn, announces truncation, explains quarantined
  answers), REQ-SI-FR-014/GOV-001 (language policy by script), REQ-SI-FR-008 (report
  stores the body; a refusal is never stored), REQ-SI-FR-006 (static gate: augmented
  assignment, aggregation calls, comprehension aliases, default-parameter keys).
- Architecture: ADR-001 Am1, ADR-002 Am1, ADR-004 Am4, ADR-006 Am8; no schema change;
  prompts/ and CI workflows untouched.
- Test quality: 34 new tests (test/offline/test_tp019_fifth_audit.py); 30 fail on the
  pre-fix tree (mutation evidence), the other 4 are positive/boundary guards; zero
  edits to existing tests; full offline suite 458 green, coverage 88%;
  ruff + mypy clean; structural gates pass; PR-mode simulation of the change-set
  gates recorded in AILOG-0065. Live re-run (deepseek-flash, same 9-turn script):
  8/9 turns as expected (was 6/9) - the remaining one is a DE-10 strictness class.
- Security: the SEC-003 loopback exception now matches 127.0.0.0/8 and ::1 as parsed
  IP literals plus the name localhost; prefix-shaped hostnames are refused (BD-021).
- Governance record: docs/ai-use-log.yaml had stopped parsing as YAML since PR #54
  (AILOG-0063/0064 at column 0, BD-025); re-indented whitespace-only with parsed content
  verified identical, and the AI-use log gate now fails on an unparsable log.
- Erratum RM-55: its "Security" line ("loopback HTTP is scoped to 127/8 + localhost +
  ::1 only") described the ADR decision, not the shipped code, which accepted any
  hostname starting with "127." (fixed here; ADR-004 Am4).
- Addendum (final-code live re-run, same script): 9/9 turns passed the post-check; turn 2
  refused the direction call with factual context, turn 6 recalled the turn-1 close, and
  the stored report holds only the report. Turn 5 showed a self-corrected cross-symbol
  table cell (0700.HK's close placed in the 9988.HK column) that the field-level typed
  pool cannot see - recorded as DE-12 for the M2 phase-2 plan.

### RM-57 — TP-020: partial-date citations (BD-026)

- Verdict: APPROVE pending owner merge (owner approved TP-020 in session, 2026-10-01, after
  the drafted plan, fix and verification were presented; TP-020 committed before any
  implementation change, GOV-006 ordering).
- Spec alignment: REQ-SI-INV-001 - correctly cited month-years and framed bare years pass
  at their written precision; unsupported references fail exactly as before; a value equal
  to an evidence year in a value frame stays a numeric claim; full dates keep day
  precision. REQ-SI-QA-001 - E-009 records the labeled cases; the E-006 suite is unchanged.
- Architecture: ADR-006 Am9; no schema change; NumberCheck gains a defaulted audit list
  (`calendar`); the degraded text, prompts/ and CI workflows untouched.
- Test quality: 12 new tests (test/offline/test_tp020_partial_dates.py) holding 25
  must-pass and 23 must-fail labeled cases, one end-to-end turn each way over the real
  market.indicators tool. Against the pre-fix guardrail 7 fail on the bug, 1 fails only on
  the new audit attribute, 4 are guards that hold on both trees. Zero edits to existing
  tests; full offline suite 470 green; ruff + mypy clean; structural gates pass.
- Risk: the bare-year rule is an allow-list of temporal frames, so its failure mode is a
  remaining false quarantine (DE-13), not an escape. Accepted consequence (owner,
  2026-10-01): a remembered year in a framed sentence passes when an evidence date falls
  in that year; every other number in the sentence is still checked.

### RM-58 — TP-021: opt-in terminal UI, phase 1 (FR-026)

- Verdict: APPROVE pending owner review and a hands-on run in Windows Terminal (owner
  approved TP-021 with ADR-007 in session, 2026-10-01; TP-021 committed before any
  implementation change, GOV-006 ordering; the golden transcript was captured from the
  pre-change tree before any code change).
- Spec alignment: REQ-SI-FR-026 (a)-(e) each pinned by named tests (TP-021 fit-criteria
  mapping). REQ-SI-FR-013: plain stays the default and is byte-identical (golden test,
  plain and `--ui tui` without a terminal). REQ-SI-INV-001: model text reaches the screen
  only through render() and the post-check-gated replay; Markdown only under render
  fidelity. REQ-SI-INV-004: the write confirmation defaults to decline and ignores every
  key but arrows/Tab/Enter/Esc/Ctrl+C/Ctrl+D; accept submits `confirm <token>` to the
  unchanged path.
- Architecture: ADR-007; new module agent/tui (agent tier, no data import; import gate
  unchanged); agent/repl keeps the only dispatcher behind the ReplIO port; agent/loop
  gains two optional hooks that carry phases and proposals, never provider text. No
  safety-critical path touched (guardrail, registry, shared/, prompts/, workflows).
  One dependency added (prompt-toolkit, with wcwidth), owner-approved; uv.lock updated.
- Test quality: 29 new tests, 20 of them with negative or adversarial cases; boundary cases for the
  Ctrl+C window (1.9 s / 2.1 s) and fidelity (1/2 kept, 1/5 and 1/3 fall back). Seven
  injected mutations each fail at least one new test. Zero edits to existing tests; full
  offline suite 499 green; ruff, mypy and structural gates pass on a clean clone.
- Risk: real-terminal rendering (Windows Terminal glyph widths, the spinner, the frame)
  cannot be verified offline - owner check before any default switch. Ctrl+C at the UI
  prompt clears input instead of ending the process (plain unchanged). DE-14 (interrupted
  turns are not marked incomplete) becomes more visible under the UI; it predates TP-021.
- Follow-up (2026-10-01, before the change set was proposed): a headless real-console
  smoke run (ConPTY, ctypes only) found BD-027, an input frame stretched to the bottom of
  the console. It is fixed (`fit_to_content`) and pinned by `test_framed_prompts_stay_compact`
  (TP-021 Amendment 1); the suite is now 30 TUI tests. The re-run in the real console
  passes 13 of 13 checks: the session opens, the status line shows its counters, the
  completion menu appears, Tab completes, `/watch list` and `/help` dispatch, Ctrl+D closes
  with the resume hint and exit code 0, the frame has no empty rows, and no fallback and
  no traceback appear. Glyph and color rendering in Windows Terminal itself remains the
  owner check.

### RM-59 — TP-022: slash write commands rejected since H3 (BD-028)

- Verdict: APPROVE pending owner merge (owner approved TP-022 in session, 2026-10-02, after
  the diagnosis, the offline reproduction and the planned fix were presented; TP-022
  committed before any implementation change, GOV-006 ordering).
- Spec alignment: REQ-SI-FR-001 - `/sync` runs the sync again from the REPL entry.
  REQ-SI-FR-004 and REQ-SI-INV-004 - `/watch add` and `/watch remove` execute only after
  the human's yes; any other answer executes nothing. REQ-SI-FR-013 - the slash commands
  and the CLI subcommands are one verb set again.
- Architecture: one file changed (`agent/repl.py`: three argument dicts and one docstring).
  The registry, the tool specs, the confirmation broker and the conversational write path
  are unchanged; the model still cannot write without a human token. No safety-critical
  path touched. The stale `register_data_tools` docstring in `agent/registry.py` is left
  for the next registry change set (noted in BD-028).
- Test quality: 6 new tests (12 cases), with positive, negative and boundary cases for the
  `[y/N]` answer, plus a structural guard that checks every literal tool call in
  `agent/repl.py` against its tool's spec. Against the pre-fix `repl.py`, 6 of 12 cases
  fail; the 6 guards hold on both trees. Zero edits to existing tests; full offline suite
  512 green; ruff, mypy and the structural gates pass.
- Risk: none new. The fix only removes an argument the registry already refused; the write
  gate and the human confirmation are as before.

### RM-60 — TP-023: INV-001 v2 phase 1, verify and flag (ADR-008)

- Verdict: APPROVE pending owner merge (owner approved ADR-008 and TP-023 in session,
  2026-10-02, after the post-check probe and the drafted records were presented; TP-023
  committed before any implementation change, GOV-006 ordering).
- Spec alignment: REQ-SI-INV-001 (changed, ADR-008) - no unverified number reaches the
  screen or the record unmarked: every occurrence of an unverified token is marked (an
  11-text battery), and a number that cannot be located for marking withholds the answer
  as before (fail-closed). Screen == record: the event stores the marked text, the
  unverified list and the unmarked original. Correctly cited numbers display unmarked; the
  existing positive suites are unchanged. REQ-SI-FR-008 and REQ-SI-QA-004 (changed) - a
  flagged report is stored with its markers and an "unverified numbers" header line; only
  a fully verified report claims the pass; a withheld report is not stored. REQ-SI-INV-002
  and REQ-SI-GOV-001 (unchanged) - the epistemic abort and the language withhold hold.
  REQ-SI-INV-003 - nothing unverified is presented as verified: the marker, the notice and
  the "flagged" footer say so.
- Architecture: ADR-008 phase 1. Safety-critical path touched: `agent/guardrail.py`
  (marking, verdict composition, counter semantics); the detector `postcheck_numbers` is
  unchanged apart from exposing the text it checked. `agent/loop.py`, `agent/repl.py` and
  `agent/tui/render.py` follow. The registry, `shared/`, `prompts/` and CI workflows are
  untouched; no dependency added. Event kinds are unchanged; the assistant-message event
  gains optional `unverified` and `original` fields and the `post_check` value "flagged"
  (forward-only; old records render and replay as before).
- Test quality: 23 new cases (positive, negative/adversarial, boundary, INV-002
  composition, terminal UI). Against the pre-change tree 22 fail; the INV-002 abort guard
  holds on both trees. Nine injected mutations each fail at least one new test. Ten
  existing files carry migrated assertions for the requirement change (TP-023 table;
  before and after in AILOG-0070); full offline suite 535 green; ruff, mypy and the
  structural gates pass.
- Self-review findings, fixed before the change set was proposed: the unverified streak
  was fed by the pre-regeneration draft, so a flagged regeneration reset it and an
  unverified number that never reached the screen counted; the counter now receives the
  number check of the answer as shown (`test_streak_follows_the_answer_as_shown`). In
  invariants.md, INV-001 fallback item 3 read "stored flagged `post_check: failed`"; it
  now reads "stored with", because "flagged" is now a `post_check` value.
- Risk: a user may act on a flagged number (ADR-008 residual risk). Mitigations: the
  marker on every occurrence, the notice, the history note and the streak notice; ADR-008
  reopens on owner observation. Until the typed engine (TP-024) accepts rounding, correct
  rounded renderings such as "about 37%" are flagged. The warning color of the notices in
  a real terminal is an owner check.

### RM-61 — TP-024: INV-001 v2 phase 2, typed claim verification (ADR-008 Am1)

- Verdict: APPROVE, pending owner merge and owner review of the held-out labels.
  - The owner approved TP-024 and ADR-008 Am1 in session on 2026-10-02.
  - TP-024 was committed first, and the held-out corpus before any engine code (GOV-006
    ordering; P6 separation).
- Spec alignment:
  - REQ-SI-INV-001:
    - fabricated and misattributed numbers are flagged by subject and field (the
      ADR-008 probe, DE-12 swaps, a seeded generated battery);
    - correct renderings verify at their written precision (rounding, scale words,
      signs, whole times, partial dates within windows, quotes of tool text);
    - only unverified claims carry the marker, each with one reason;
    - the fail-closed withhold remains.
  - Known gap: company names the ledger cannot resolve (DE-16), waived by the owner and
    deferred to TP-025.
  - REQ-SI-QA-001: E-010 recorded. REQ-SI-FR-022: `/show` lists each unverified number
    with its reason.
- Architecture:
  - New module `agent/guardrail_claims.py`, inside the safety prefix.
  - `guardrail.py` keeps every v1 helper and the `NumberCheck` shape, with two new
    fields; the v1 check stays available as `postcheck_numbers_v1`.
  - The loop marks from the verdict's claims.
  - Registry 0.6.1 changes the regression scope only.
  - Unchanged: tool results, `shared/`, `prompts/`, CI workflows.
- Test quality:
  - 55 new cases. Against the pre-change tree 36 fail; 19 guards hold on both trees.
  - Ten injected mutations are each caught.
  - The held-out first run was recorded before any refinement; every refinement is
    pinned by a development item.
  - Migrated assertions are listed in AILOG-0071 (one found during implementation and
    approved by the owner).
  - Full offline suite green; ruff, mypy and the structural gates pass.
- Risk:
  - Heuristic field and subject typing (DE-15): a misread cue shows as a flag.
  - Company names (DE-16).
  - The post-fix held-out numbers are not independent.
  - An unfielded number keeps v1 semantics (P2), so its escapes are v1's.
