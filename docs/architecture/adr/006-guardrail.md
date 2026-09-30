# ADR-006 — Runtime Guardrail: INV-001 Post-Check and INV-002 Epistemic Filter

| Field | Value |
|---|---|
| ADR | 006 |
| Date | 2026-09-16 |
| Status | accepted (owner-approved with TP-006) |
| Related | `docs/architecture/invariants.md` (INV-001/002/003 fallback semantics); ADR-001 §6 (provenance ledger); ADR-004 (`shared/`); ADR-005 (provenance triple); blueprint §11 (verdict stream) |
| Change set | TP-006 (`docs/test-plans/TP-006.md`) |

## 1. Decision

`agent/guardrail.py` is the runtime executor of the two core invariants, as a fully testable verdict library; the agent loop (TP-007) wires it into the response pipeline. Six rulings:

1. **Exact-after-normalization number matching (INV-001).** Every numeric token in a candidate response (thousands separators stripped; int/float equivalence canonicalized) must appear in the response's context-snapshot value pool — itself composed from tool results carrying the ADR-005 provenance triple. **Derived numbers are not accepted**: sums, differences, and growth rates must be computed by a `compute`-class tool and land in the snapshot; arithmetic appearing only in prose is a violation. Precision over convenience.
2. **±1 is a failure, not a tolerance.** The registry semantics (boundary ±1 cases in `test_inv1_postcheck.py`) are literal: 311.4 cited against a 311.5 snapshot fails.
3. **Pattern-library epistemic filter v1 (INV-002), precision-first.** Two deterministic pattern families — deterministic prediction and causal claim — plus hypothesis-marker recognition (a violating sentence survives only when labeled). The library is deliberately over-strict; its recall limits are a documented liability measured when the filter enters the live pipeline (eval-set extension with epistemic cases + precision/recall recording in the evaluation logbook at TP-007+). Measuring it now would evaluate a filter the pipeline does not yet run — deferred honestly.
4. **Fallback semantics exactly per the invariant document.** INV-001 failure: quarantine (never display the original; the loop stores it flagged `post_check: failed`), degrade to `data unavailable for: <list>`, session continues; three consecutive failures abort. INV-002: strip violating passages, one regeneration attempt with an injected constraint reminder, then explicit refusal with a hypothesis-labeled safe summary; more than two violations per session abort. `PostCheckCounter` implements both budgets; `run_with_regeneration` implements the strip-once-regenerate-once-refuse flow with the regenerator injected (no LLM coupling in tests).
5. **Language policy is part of the verdict** (INV-003 surface): a non-English response quarantines with an explicit withheld statement (`shared/language` per ADR-004).
6. **Verdict composition:** `run_postcheck` is single-pass and authoritative (INV-001 + INV-002 + language); quarantine takes display precedence over epistemic stripping. The loop composes regeneration only for non-quarantined verdicts with epistemic violations.

## 2. Alternatives Considered

- **LLM self-critique for INV-002** (ask the model whether its output is safe): rejected — judging model output with the same model class hollows out the invariant; the guardrail must be deterministic and inspectable.
- **Numeric tolerance windows** (±ε, string similarity): rejected — the registry's ±1 boundary semantics are exact; tolerances invite drift.
- **Full NLP causal parsing** (dependency parses, causal cue taxonomies): deferred — the pattern library covers the deterministic surface; reopen if live precision falls below 0.9 or a recall incident is recorded.
- **Fuzzy number-to-source alignment** (mapping each number to a specific source record): deferred — v1 checks pool membership; per-number source attribution arrives with the provenance-ledger integration in the loop TP.

## 3. Consequences

- Analyst-toned prose ("will likely recover") may trip the filter when unlabeled — the regeneration path and hypothesis markers are the intended mitigation; user guidance belongs in the identity prompt (TP-007).
- Years, dates, and identifiers in output are numeric tokens under INV-001 and must be snapshot-backed (strict by design; the snapshot carries the data dates the report cites).
- The counter library trusts its caller (the loop) to record every verdict; TP-007's wiring tests close that seam.
- QA-004 measurement hooks (post-check verdict stream) consume the verdict data structure this ADR fixes.

## 4. Reopen Conditions

- Live precision/recall measurement at loop integration (TP-007): pattern-library extension or NLP adoption per threshold above.
- Per-number source attribution (provenance ledger consumption).
- Derived-number support only via registered compute tools — never by relaxing the post-check.
- New fallback thresholds are invariant-document changes, not code tweaks.

## Amendment 1 (2026-09-21) — BD-012: display-rounding allowance in the numeric match

INV-001's exact-after-normalization match predates contact with real
vendor data, where indices and adjusted closes carry four decimals
and models render two. The postcheck correctly refused the
transformed values — but refusing a standard decimal rendering of a
pooled value turns every conversational quote into a false
quarantine. Refined semantics: a token with exactly d decimals
(d in 2..4) matches a pool value within half an ulp of that decimal
place; such tokens are tracked as `rounded` in the NumberCheck for
audit. This is a rendering convention, not a numeric tolerance:
integer-scale deviations (the ±1 adversarial class) still fail —
zero- and one-decimal tokens never display-round-match, and the
bound tightens with d (a truncation like ...241 against ...2402
exceeds the d=3 bound). The identity prompt (v3) instructs exact
rendering as belt-and-braces. The adversarial suite grows four
cases pinning the allowance's edges.

## Amendment 2 (2026-09-24) — BD-015: percent-display allowance

Live analysis over the indicator snapshot: the model cited
0.18573119 (exact) and added "about 18.57%" as a reading — a
fraction-to-percent conversion with rounding, mechanically
untraceable, semantically faithful. Refined: a token equal to a
pool value x 100 within half an ulp of its 2-4 decimal rendering
matches when (and only when) a percent marker (%, percent, pct)
is adjacent to the token in the response text. Bare numbers never
qualify for the conversion match, so the integer-scale
adversarial classes (the +/-1 family) fail exactly as before;
percent readings of non-fractional pool values are harmless but
admitted. Percent-display matches are tracked in the same
`rounded` audit list. The identity prompt (v4) instructs citing
the fraction as returned; the allowance is for the reading, not
the citation.

## Amendment 3 (2026-09-24) — BD-016: enumeration markers are layout

The first live /report run numbered its "Known gaps" section; the
ordinals ("1." .. "6.") were extracted as numeric tokens, matched
nothing in the pool, and quarantined an otherwise fully-cited
report through both the original and the regenerated response.
Enumeration markers are document structure, not cited values:
before extraction, a line-leading marker of one to three digits
followed by a period or paren and whitespace is stripped. Genuine
line-start values are safe by construction — a cited number keeps
its decimals ("24879.2402" cannot match) and four-digit years
exceed the marker width. Inline parenthetical references in prose
are untouched (conservative: only line-leading markers strip).

## Amendment 4 (2026-09-27) — BD-018: ISO dates fold to the pool's form

The first live news-analysis turn cited headlines with ISO dates
(2026-09-23) while the pool carries GDELT-style compact seendates;
the extractor read the hyphenated form as a year plus orphaned
month/day fragments (-09, -23) that matched nothing, quarantining
an otherwise fully-cited analysis. Fix: before extraction, an ISO
calendar date (exactly 4-2-2 digit groups, not embedded in longer
numbers) folds to the compact YYYYMMDD form — which is precisely
the token the pool already yields from seendate strings. This is a
rendering-convention alignment (same family as BD-012/015/016),
not a tolerance: no numeric comparison changes, and the adversar-
ial classes are unaffected (a fabricated compact date still must
match the pool exactly).

## Amendment 5 (2026-09-29, TP-018) — verify-then-display covers the whole turn; the pool is a session ledger with turn-scoped keys

Two third-audit findings close here.

(1) Prelude coverage. TP-017 PR-1 buffered provider deltas and
replayed them only after the post-check — but only the FINAL
iteration's text was checked: opening text emitted before tool calls
streamed through unvalidated (and never entered session.jsonl, so
screen and record diverged). Correction: every per-iteration provider
text accumulates as a prelude; the post-check validates
prelude + candidate as one string; the replay shows exactly what was
validated; the assistant-message event stores the same full text.
FR-019's "streaming" rendering is therefore "verified replay":
deltas reach the user only after the whole turn's numbers pass.

(2) Turn-scoped ledger keys. The cross-turn ledger (PR-3a) merged
snapshots under keys `tool#seq` with a per-turn seq counter, so a
later turn's `market.quote#1` evicted an earlier turn's — a
BD-019-class collision at session scope. Keys become
`turn-NNNN/tool#seq`; the session merge is a true union and earlier
turns' numbers stay citable (with turn attribution already in the
artifact files). INV-001's wording moves from "this response's
snapshot" to "the session's evidence ledger (per-turn snapshots,
turn-scoped keys)"; invariants.md records the change.

## Amendment 6 (2026-09-29, TP-018) — heading ordinals: two digits, punctuated or bare, nothing larger

Am3 exempted heading ordinals of one to three digits with optional
punctuation. The audit showed the bypass: `## 850 HKD fair value`
stripped "850" as if it were a section number, while the same number
in prose was checked. Headings rarely number past 99; ordinals now
strip only at one to two digits (`#{1,6} 12. Title`, `## 6 Summary`).
A three-digit leading heading number is treated as a numeric claim
and must trace like any other (a false quarantine there is the
price of closing the bypass; document section numbers >= 100 are
vanishingly rare in this product's output classes).

Also recorded here (same change set): the INV-002 filter gains a
reported-speech exemption (attribution markers — said, announced,
guidance, according to — exempt prediction-pattern sentences as
reporting, fixing the "Management said it will increase the
dividend" false positive) and new prediction classes for recall
(likely to / set to / on track to / expected to / forecast to);
E-007's measured P/R moves to a separately-authored adversarial
battery (the previous 1.00/1.00 was measured on sentences written
by the same author as the patterns). Phase 1 of typed numeric
provenance (M2): the pool carries (tool, field) per value, and the
OHLCV mismatch class — a sentence naming one OHLCV field whose
number matches only a different OHLCV field's value — fails the
check ("open quoted as close"). Remaining semantic gaps are a
documented limitation until phase 2.

## Amendment 7 (2026-09-29, TP-018b) — Am6 code/doc reconciliation + fourth-audit corrections

The fourth audit caught Am6 claiming things the code did not do, plus
three real defects. All four are corrected here and pinned by tests:

1. "expected to" is now actually implemented (modal class gains
   expected/predicted/projected/anticipated; verbs gain
   reach/exceed/double/triple). Am6's original text claimed it; the
   code did not have it.
2. Attribution exemption narrowed (fourth-audit laundering finding):
   REPORTED speech requires BOTH a reporting speech-act verb (said,
   announced, ...) AND an institutional source noun (management,
   company, filing, ...), or an explicit "according to the
   <document/company>" form. "According to the chart" no longer
   exempts anything. The Am6-era single-marker exemption is retired.
3. Heading ordinals: only a punctuated 1-2 digit ordinal or a single
   bare digit is layout; "## 85 USD price target" is a numeric claim.
4. Identifier codes (GOV-001, ADR-005, TP-018, Am2, Q1, SP500) are
   blanked before number extraction: a letters-hyphen-digits or short
   letters-glued-digits token is a reference, never a cited value.
   Field mentions tokenize as identifiers, so snake_case table rows
   ("| adjusted_close | 642.8959 |") resolve to their field instead
   of mis-attributing the neighboring "close" row's word.

Known phase-2 limitations, recorded honestly (not claimed fixed):
word-form numbers ("eighty percent"), non-OHLCV semantic swaps
(drawdown quoted as volatility), "18.57 (vs 3% margin)" context
class, and 1-decimal percent display. These remain open for a
dedicated test plan.

E-007a authorship note: the adversarial battery sentences are
ADAPTATIONS of the audit's reported violation classes written by the
remediation author - not verbatim auditor sentences. A truly
auditor-authored held-out set remains the reviewer's instrument.

## Amendment 8 (2026-09-30, TP-019) — closed identifier set; speech-act attribution; clause-local hedges; a real regeneration request

The fifth audit found that two Am7 corrections opened new holes and
that the regeneration path never worked as §4 describes. Corrections:

1. Identifier codes: a closed set, not a shape. Am7 blanked any
   letters-hyphen-digits or 1-3 letters glued to 1-4 digits before
   extraction, so "closed at HKD777", "USD1200", "PE35", "RMB500" and
   "YTD-12%" were never checked - an INV-001 bypass. Only these
   reference shapes are blanked now: `REQ-SI-XX-NNN`; the governance
   prefixes GOV/ADR/TP/INV/BD/RM/PR/FR/QA/PERF/COST/SEC/AILOG with a
   hyphenated number; `AmN`, `Q1`-`Q4`, `H1`/`H2`, `FYnn(nn)`, `vN`;
   and benchmark names whose digits are part of the name (S&P 400/500/
   600, SP500, Nasdaq-100, COVID-19). Digits glued to anything else are
   extracted and checked. Boundary: `Q4` is a label, `Q5` is not.
2. Natural-language calendar dates ("September 23, 2026", "23 Sep
   2026") fold to the compact YYYYMMDD form, extending BD-018/Am4: a
   correctly cited date no longer quarantines as "23" and "2026"; a
   date absent from the ledger still fails.
3. The OHLCV alias "vol" is removed (Am7 added it): in market prose it
   abbreviates volatility, and it mis-typed nearby prices as volume.
4. Attribution is a speech act by an institutional source. Am7
   accepted any reporting-or-inference verb plus any source noun
   anywhere in the sentence ("The chart suggests the company will rise
   20%", "According to the report, the stock will rise" passed). Now
   the source (management, the company, the issuer, the board, the
   CEO/CFO/chairman, a spokesperson, the filing, the earnings/press
   release, the statement/announcement/prospectus, guidance, the
   regulator, the exchange) must be the ADJACENT subject of a speech
   verb (said, announced, stated, declared, reported, guided,
   confirmed, disclosed), and either precede the claim inside the same
   clause, or close the whole sentence as a tag (", the filing
   states."). Inference verbs (suggests, indicates, notes, shows) and
   bare generic nouns (report, chart, analysis) never attribute;
   "according to" keeps only institutional objects.
5. Hedges are clause-local. An explicit label ("Hypothesis:",
   "speculative") still covers its sentence; a modal hedge (might,
   could, may, possibly, perhaps) covers only its own clause
   ("Revenue may dip, but the stock will double" is a violation). The
   modal "may" is matched lower-case only: the month in "In May the
   stock will rise" is not a hedge.
6. Recall batch: unambiguous price-direction verbs (double, triple,
   soar, tumble, crash, plunge, rebound, skyrocket, outperform,
   underperform) join the base verb set; new classes cover an adverb
   between "will" and the verb ("will likely rise"), effect-first
   causal claims ("fell 5% due to"), driver verbs ("drove the price
   higher"), passive causation ("was caused by"), price targets
   ("should hit 700", "headed for 800") and expectation nouns ("expect
   a rebound"). Ambiguous verbs (gain, lose) stay out for precision.
7. The regeneration request (§4 "one regeneration attempt with a
   strengthened constraint reminder"). The loop used to send ONLY the
   stripped draft, as a USER message, with no identity, question or
   conversation; the live model answered "that looks like my previous
   answer pasted back" and that text was displayed and recorded as the
   answer. The request now replays the turn's conversation (identity,
   history, the user's question; tool-call plumbing omitted - the
   recheck verifies every number against the session ledger), hands
   the stripped draft back as the ASSISTANT's message, and adds one
   harness instruction carrying the reminder. An empty regeneration
   refuses. Every regeneration writes an `error`/`epistemic` event with
   the violating original, the violations and the outcome
   (regenerated / refused / regenerated-quarantined): the session log
   used to show only the replacement text with post_check "ok". A
   refusal is not a report: /report stores nothing for it, and stores
   the answer body without the pre-tool prelude.

Known limits recorded (not claimed fixed): a hedge governing a
different verb in the same clause ("We could see that the price will
rise") still labels the claim; a fabricated attribution tag is beyond
a regex; counts and tickers absent from the ledger ("3 symbols",
"9988.HK") keep failing by the standing TP-017 PR-3a decision.

Implements: REQ-SI-INV-001, REQ-SI-INV-002, REQ-SI-FR-008, REQ-SI-FR-011.
