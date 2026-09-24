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
