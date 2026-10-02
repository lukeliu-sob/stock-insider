# ADR-008 — Numeric verification v2: verify and flag, typed claims

| Field | Value |
|---|---|
| ADR | 008 |
| Date | 2026-10-02 |
| Status | accepted (owner-approved with TP-023, 2026-10-02; decisions 1-3 taken in session the same day) |
| Related | REQ-SI-INV-001, REQ-SI-FR-008, REQ-SI-QA-004; ADR-006 (ruling 1 kept; ruling 4 and the INV-001 match amendments Am1-Am9 superseded in phases); ADR-007 (verify-then-display, render fidelity); invariants.md INV-001; runtime policy P-07; DE-10, DE-12, DE-13 |
| Change sets | TP-023 (phase 1), TP-024 (phase 2), TP-025 (phase 3) |

## Context

On 2026-10-02 two live answers about BYD were withheld whole, each for a
single number:

- `123202178`: a news timestamp written to the millisecond
  (`20260929T123202178Z`); the evidence holds `20260929T123202Z`.
- `37`: "roughly a 37% annualized swing rate", for an evidence
  volatility of 0.3711553760998695.

Everything else in both answers was correct:

- exact quotes;
- exact risk metrics;
- an honest account of the missing fundamentals;
- no buy or sell call;
- hypotheses labeled as such.

A probe of the post-check on the same day (realistic ledger, current
code):

| Answer text | Evidence | Result |
|---|---|---|
| `traded 18.98 million shares` | volume 18982584 | withheld |
| `fell 36.09% from its peak` | max drawdown -0.36087947 | withheld |
| `volatility is about 37%` | volatility 0.37115537 | withheld |
| `published at 2026-09-29 12:32:02 UTC` | timestamp `20260929T123202Z` | withheld (12, 32, 02) |
| `BYD trades at a P/E of 18` | no P/E evidence; 18 is a news count | passed |
| `0700.HK closed at 75.6` | 75.6 is the close of 1211.HK | passed (DE-12) |
| `BYD's net margin is 0.998` | 0.998 is a news sentiment score | passed |
| `quarterly revenue was 380,000 million yuan` | 380,000 is from a news title | passed |

Root cause: one mechanism serves every digit in an answer.

- A single regular expression extracts every digit run.
- One flat, untyped pool holds every number in the session's evidence,
  including digits inside news titles and URLs, and pool membership
  decides each run.
- Dates are folded into digit strings and checked against the same pool.
- Typing exists only for OHLCV field names, at field level (DE-12).

Amendments 1-9 each exempted one more rendering. The result is strict
on how a number is written and loose on what it is claimed to be.

Owner decisions, 2026-10-02:

1. Replace pool membership with typed claim verification.
2. Rounding to any written precision, whole numbers included, is an
   allowed rendering: it is not a change to the data.
3. Show the answer and point out the numbers that may be wrong, instead
   of withholding it.

## 1. Decision

1. **Verify and flag.** Every numeric claim is still verified before
   display; verify-then-display is unchanged (ADR-007 §1.6a). A claim
   that cannot be verified no longer withholds the answer:
   - The answer is shown with the marker `[?]` at the end of each word
     that holds an unverified number.
   - A harness notice lists the unverified numbers and why they did not
     verify.

   The invariant becomes: **no unverified number is displayed or stored
   without its marker** (zero tolerance on unmarked unverified numbers).
   - **Fail-closed fallback.** If an unverified number cannot be
     located in the text to be marked, the answer is withheld as before.
   - **Record.** The marked text is the displayed text and the recorded
     text (screen == record). The assistant-message event carries
     `post_check: "flagged"` and the list of unverified numbers.
   - **Model history.** The history replays the marked text with a
     harness note naming the unverified numbers, so a later turn does
     not restate them as fact. Unverified numbers never enter the
     evidence ledger (unchanged: the ledger holds tool results only).
   - **Reports (FR-008).** A report with unverified numbers is stored
     with its markers and a header line counting them. Only a report
     whose every number verified carries the "passed the post-check"
     line.
   - **Session abort.** The INV-001 three-strike abort is retired.
     Three consecutive answers with unverified numbers show a
     non-blocking notice instead.
   - **Unchanged:**
     - INV-002 (strip, one constrained regeneration, refusal, abort
       budget);
     - the language-policy withhold (GOV-001);
     - derived numbers (sums, differences, changes) must come from
       compute tools; they are flagged when they do not.
2. **Typed claims.** Every number in an answer is classified by a
   deterministic grammar before it is checked:
   - structural (list and heading numbering);
   - identifier (tickers, versions, URLs);
   - temporal (dates, timestamps, quarters, fiscal years, windows);
   - quoted text;
   - quantitative.

   A number that fits no class is quantitative and matches exactly
   only. Evidence is indexed by type: value, field class, unit, symbol,
   date and source. Digits inside free text (titles, URLs) count as
   evidence only for quoted text.
3. **Quantitative claims match within typed candidates.**
   - The subject (symbol) and the field come from context: field cues,
     the nearest subject, table row and column headers. The claim is
     compared only with evidence of that subject and field class.
   - Equivalences at the written precision:
     - units (fraction and percent, basis points);
     - scale words (thousand, million, billion);
     - the sign of a decline;
     - rounding to the written precision, whole numbers included (owner
       decision 2).
   - A field cue without matching evidence, or a subject mismatch, is
     unverified. Examples: "P/E of 18" with no P/E evidence; a close
     attributed to the wrong symbol.
   - With no identifiable field, the claim needs an exact match against
     the pool, so the rule is never looser than v1.
4. **Temporal claims** are parsed whole and checked against evidence
   times at the written precision. A claim more precise than its
   evidence is unverified, with that reason. Supported forms:
   - ISO, compact and natural forms;
   - fractions of a second and time zones;
   - quarters, fiscal years, month-years and windows.
5. **Reasons are recorded per claim** and shown in the notice and in
   `/show`. Example reasons:
   - no evidence for field X of symbol Y;
   - value differs;
   - more precise than the evidence;
   - derived value.
6. **Phasing.**
   - Phase 1 (TP-023): verify and flag, using the current detector.
     Answers stop being withheld at once; the current over-strict cases
     appear flagged instead of withheld. Rounding acceptance waits for
     phase 2: against the current global pool, a whole-number tolerance
     would verify many unrelated values (dozens of floats per session:
     prices, sentiment scores).
   - Phase 2 (TP-024): the typed engine (decisions 2-5). It removes the
     false flags of the probe table, flags its four misattributions,
     and closes DE-12, DE-10(c) and DE-13.
   - Phase 3 (TP-025): tools declare the semantics of their result
     fields in `shared/` (ADR-004 amendment), replacing heuristic field
     typing.

## 2. Alternatives Considered

- **Keep withholding (status quo).** Rejected by the owner: one
  rendering deviation destroys a correct answer, and live sessions keep
  hitting this.
- **Targeted regeneration before withholding.** Rejected in favor of
  flagging: it adds latency and cost to every failure, and still
  withholds when the second draft fails.
- **Sentence-level redaction.** Rejected: it hides content the user may
  need, and it changes screen == record semantics more than markers do.
- **Whole-number tolerance against the current global pool.** Rejected:
  a fabricated integer would often fall within half a unit of some
  unrelated value.
- **LLM judge or self-critique.** Rejected, as in ADR-006 §2: the
  verifier stays deterministic.
- **Structured citations** (the model cites evidence keys). Deferred: it
  gives the most precise attribution, but needs prompt and renderer
  changes. Reconsider after the phase-2 data.

## 3. Consequences

- **Requirement changes.** Registry discipline rule 1 applies: a row
  change needs an ADR and a regression rerun. Affected:
  - REQ-SI-INV-001 statement and fit criterion;
  - the registry `scope_must_not_do` item on unverified numerics;
  - REQ-SI-FR-008 and REQ-SI-QA-004 (flag instead of degrade);
  - invariants.md INV-001 and runtime policy P-07;
  - AGENTS.md §2b;
  - the glossary (Post-check, Unverified Marker).
- **Test migration.** About sixteen offline suites assert withholding
  for numeric mismatches. TP-023 rewrites them to the flag semantics as
  a requirement change, not a regression fix, and lists every rewritten
  assertion. Detection tests (which tokens fail) keep their assertions
  in phase 1.
- **Residual risk.** A user may act on a flagged number. Mitigations:
  - the marker sits on the number itself;
  - the notice names it and gives the reason;
  - stored reports keep the markers.
- **Abort protection.** The INV-001 abort no longer stops a session
  whose model keeps inventing numbers; the notice replaces it.

## 4. Reopen Conditions

- Users act on flagged numbers (owner observation): reconsider
  withholding for specific claim classes, for example valuation ratios
  without evidence.
- The phase-2 false-flag rate on the labeled live corpus exceeds the
  owner's threshold.
- Structured citations become cheap enough to adopt.
