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
