# ADR-008 — Numeric verification v2: verify and flag, typed claims

| Field | Value |
|---|---|
| ADR | 008 |
| Date | 2026-10-02 |
| Status | accepted (owner-approved with TP-023, 2026-10-02; decisions 1-3 taken in session the same day); Amendment 1 (phase 2) approved with TP-024, 2026-10-02 |
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
     fields in `shared/` (ADR-005 Amendment 4, not ADR-004 - ADR-004
     deferred tool I/O schema design to ADR-005 by its own §4; corrected
     2026-10-03), replacing heuristic field typing.

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

## Amendment 1 (2026-10-02, TP-024) — phase 2: the typed claim engine

Status: approved with TP-024 (owner, in session, 2026-10-02). Owner
decisions P1-P7 were taken in session the same day ("as recommended",
translated).

### Context

Phase 1 (TP-023, #59) flags instead of withholding, using the v1 detector. A
baseline run on main 97b4a88 with a ledger shaped like real tool results:

| Answer text | Truth | Phase 1 | Phase 2 |
|---|---|---|---|
| `1211.HK traded 18.98 million shares.` | correct | flagged | verified |
| `1211.HK fell 36.09% from its peak.` | correct | flagged | verified |
| `Volatility is about 37%.` | correct | flagged | verified |
| `published at 2026-09-29 12:32:02 UTC` | correct | flagged (12, 32, 02) | verified |
| `BYD trades at a P/E of 18.` (18 is a news count) | fabricated | passed | flagged |
| `0700.HK closed at 75.6.` (the close of 1211.HK) | misattributed | passed | flagged |
| `BYD's net margin is 0.998.` (a sentiment score) | fabricated | passed | flagged |
| `Quarterly revenue was 380,000 million yuan.` (digits of a news title) | fabricated | passed | flagged |
| `published 20260929T123202178Z` (live; the evidence has seconds) | invented precision | flagged | flagged, reason "more precise than the evidence" |
| `roughly a 37% annualized swing rate` (live) | correct | flagged | verified |
| comparison table, 0700.HK column holding 1211.HK's close (DE-12) | misattributed | passed | flagged |
| `2025 was a volatile year for 1211.HK.` (DE-13) | correct | flagged | verified |
| `The volatility window runs from 2025 to 2026.` (DE-13) | correct | flagged | verified |
| `Volatility was elevated in November 2025.` (inside the window, DE-13) | correct | flagged | verified |
| `1211.HK closed at 76.` (close 75.6) | correct rounding | flagged | verified |

### Decisions

1. **Placement.** The engine is a new module,
   `src/stockinsider/agent/guardrail_claims.py`, inside the safety-critical
   prefix `agent/guardrail`. `postcheck_numbers()` keeps its signature and
   every `NumberCheck` field and delegates to it. The registry, `shared/`,
   `data/` and `prompts/` do not change.
2. **Claims, not tokens.** The answer is read once, on its original text;
   layout and identifiers are blanked to the same length, so every claim
   keeps its position. Each digit run belongs to exactly one claim or one
   exempt span; none goes unclassified.
3. **Classes**, assigned in this order:
   - structural: list and heading numbering (BD-016, Am6; unchanged);
   - identifier: the Am8 closed set (governance IDs, period labels Q1-Q4,
     H1/H2 and FY labels, versions, benchmarks), URLs, and symbol-shaped
     tickers (`0700.HK`, `AAPL.US`) whether or not the ledger holds them (P4,
     P7);
   - quoted: a number inside a quoted span of three or more words;
   - temporal: decision 6;
   - quantitative: everything else (fail-closed).

   Number words followed by a percent, scale, currency or unit word ("eighty
   percent", "two million shares") are quantitative claims too (P5); other
   number words ("two reasons") are not claims.
4. **Typed evidence index.** Built from the session ledger:
   - Each numeric leaf, and each string that is only a number, becomes an
     entry with value, field class, unit, currency, subject and source.
   - Field class: from the leaf key; for a generic key (`value`) from the
     sibling `metric` or the parent key; mapped through the TP-024 vocabulary.
     Keys outside it have class `unknown` and stay compatible with any field
     until phase 3 declares field semantics.
   - Subject: the result's `symbol` (or `canonical_symbol`, or the news.search
     `bucket`); session-level results (budget, sync status) have none.
   - Unit: the sibling `unit` (fraction, ratio); OHLC prices carry the row's
     currency; volume counts shares.
   - Fields a tool reported as unavailable are recorded per subject.
   - List lengths become count entries typed by the list (watchlist symbols,
     news items, search results, sync gaps, stored fundamentals rows) (P4).
   - Free text (strings with words: titles, notes, URLs) is indexed
     separately and serves only quoted claims (P3).
   - Temporal evidence: strings that parse wholly as a date or a datetime,
     with their precision; windows are mappings with `from` and `until`.
5. **Quantitative claims.**
   - Subject: a table column or row header naming a subject; otherwise the
     nearest subject mention in the same sentence, preceding first, then
     following; otherwise the nearest preceding one in the paragraph;
     otherwise none, which matches any subject. Mentions are the evidence
     symbols, their bare codes, and the first word of an evidence
     `official_name` when it is unique. In a sentence with "respectively",
     the k-th number pairs with the k-th subject.
   - Field: the table row or column label; otherwise the nearest field cue
     in the same clause, on either side of the number; otherwise none.
   - Value: an explicit minus sign; a decline word compares the magnitude
     with a negative value (a rise word against a negative value does not
     match); percent and fraction (a percent marker is still required, BD-015);
     basis points; multiples (`x`, `times`); thousand, million, billion and
     trillion; a stated currency must equal the row currency.
   - A fielded claim is compared only with entries of its subject (any, if
     none) and of a compatible field class. It verifies when
     |claim - evidence| is at most half a unit of the last written digit,
     whole numbers included (owner decision 2). Trailing zeros of an integer
     written without a scale word count as significant: "19,000,000 shares"
     claims exactness, "19 million shares" does not.
   - An unfielded claim keeps the v1 rule (exact after normalization, BD-012
     display rounding at 2-4 decimals, marker-gated BD-015 percent) against
     every non-free-text entry, so it is never looser than v1 (P2).
6. **Temporal claims.**
   - Parsed whole: ISO, compact and natural dates and datetimes; fractional
     seconds; zones Z, UTC, GMT, explicit offsets, HKT, EST and EDT (a time
     without a zone is read as UTC, as the evidence stamps are); times of day,
     attached to the date in the same sentence or else compared with every
     evidence time; month-years; ISO year-months; quarters with a year;
     framed years (TP-020 frames kept); year ranges.
   - Compared in UTC at the written precision. A claim more precise than the
     evidence it otherwise matches is unverified, with that reason.
   - Window membership (P1): a month, quarter or year verifies when it
     overlaps an evidence window of its subject (any subject, if none). A day
     must equal an evidence date.
   - DE-13: a year is also temporal when it is the subject of its sentence
     ("2025 was ...", "2025 saw ..."), when it sits in a table cell whose row
     or column label is a time word (Year, Date, Period, As of), or when it
     is a member of a from/to/between range in a clause with a time cue
     (window, period, history, data, measured, covers) and no value cue.
     Every other bare year stays quantitative (fail-closed).
7. **Quoted claims** verify when the quoted span, normalized for case,
   spacing, quote and dash forms, appears in a free-text evidence string.
8. **Marking by claim position.** The same digits can be verified in one
   place and unverified in another, and the INV-001 fit criterion requires
   correctly cited numbers to display unmarked. The marker therefore goes
   after the word that ends each unverified claim (`March 2024[?]`,
   `2026-09-28[?]`, `eighty percent[?]`). Dates become markable; the
   fail-closed withhold remains for a claim position that cannot be located.
9. **Reasons, notice, record and `/show`.**
   - Each unverified claim carries one reason, chosen in this precedence:
     - the tool reported the field unavailable for that subject;
     - no evidence for that field (of that subject);
     - the value belongs to another subject (new audit list
       `subject_mismatch`);
     - the value is another field of the same subject (`field_mismatch`, as
       in v1);
     - the value differs (with decline, rise and currency variants);
     - a derived value (a change cue and no compute-tool result);
     - more precise than the evidence;
     - no evidence date or period;
     - appears only in tool text (quote it to cite it);
     - quoted text not found;
     - not found in this session's tool results (unfielded; the phase-1
       wording).
   - The notice groups claims by reason:
     `unverified (<reason>; marked [?]): <claims>`, groups joined by `; `.
   - The assistant-message event adds `unverified_detail` (claim, class,
     subject, field, reason); `unverified` keeps the claim surfaces.
   - `/show` lists each unverified claim with its reason.
10. **Measurement (E-010).** A development set (this probe, the live BYD
    shapes, the DE classes) and a held-out set written by a separately
    briefed agent session with no access to the engine, labels reviewed by
    the owner and committed before the engine code (P6). Recall on
    fabrications and misattributions must be 1.00 on both sets. Precision on
    correct renderings must be 1.00 on the development set and at least 0.90
    on the held-out set, with every false flag pinned by name as a residual.

### Owner decisions (2026-10-02, as recommended)

- P1: window membership counts at month, quarter and year precision; a day
  must match an evidence date.
- P2: unfielded claims keep the v1 rules.
- P3: ADR-008 decision 2 confirmed: title, note and URL digits verify only
  quoted text.
- P4: DE-10 (a) and (b) are taken into phase 2: counts verify against list
  lengths; symbol-shaped tickers are identifiers.
- P5: number words with a percent, scale, currency or unit word are claims.
- P6: the held-out set is authored by a separately briefed agent session and
  reviewed by the owner.
- P7: Q1-Q4 and H1/H2 without a year, and FY labels, stay identifiers.

### Alternatives considered

- **Mark every occurrence of a token (phase 1).** Rejected for phase 2:
  verification becomes per claim, so token marking would mark correctly
  cited numbers.
- **Treat `unknown` evidence keys as incompatible.** Rejected until phase 3:
  session-level and synthetic results carry keys outside the vocabulary, and
  this would turn correct citations into flags.
- **A global whole-number tolerance.** Still rejected (ADR-008): rounding
  applies only inside typed candidates.
- **Structured citations.** Still deferred (ADR-008 §2).

### Consequences

- Stricter on meaning: misattributions, valuation ratios without evidence
  and headline digits cited as data are flagged. Looser on form: rounding,
  scale words, signs, times and partial dates verify.
- Detection assertions encoding v1 rendering strictness change as a
  requirement change; TP-024 lists each one. Any other change found during
  implementation stops the work for an owner decision.
- Field and subject typing is heuristic until phase 3 (DE-15). When a cue
  is misread, the visible failure is a flag, not an escape: an unfielded
  claim behaves as in v1.
- Headline numbers must be quoted to verify.

Implements: REQ-SI-INV-001, REQ-SI-FR-008, REQ-SI-QA-004.
