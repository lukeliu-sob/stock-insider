# Evaluation Logbook — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/architecture/evaluation-logbook.md` (course deliverable D2.9, optional — maintained) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Related | `evaluation-table.md`; `docs/req/requirements.yaml` QA-001 |

Accumulated evidence behind architecture choices. Two entry classes:

- **Q-entries (qualitative)**: decision-trail evidence from owner-supervised discussions. Complete for the current baseline.
- **E-entries (empirical)**: quantitative evidence from evaluation-set replays and runtime measurements. Appended as development proceeds — none yet; the first E-entry is expected when the evaluation harness runs against the first working pipeline.

## Q-entries (decision trail)

### Q-01 — Runtime architecture: self-built loop, in-process data side
- **Date**: 2026-09-15 · **Question**: how to build the agent runtime and deploy the data side?
- **Evidence used**: requirement weights (INV-001..004 dominate), course governance needs (context engineering must be ours), single-user deployment shape; comparison recorded in `evaluation-table.md` §1–2.
- **Outcome**: ADR-001. **Confidence**: high on governance fit; medium on maintenance cost (we own the loop).
- **Would change the assessment**: framework verifiable guardrail hooks; multi-user requirement.

### Q-02 — Data vendor: EODHD; news: GDELT + whitelist crawler
- **Date**: 2026-09-15 · **Question**: commercial fundamentals source and news path?
- **Evidence used**: HK fundamentals coverage criterion (FR-002, 99% fields), statelessness for offline tests, cost tolerance (owner accepts paid tiers), future Chinese-source extensibility; `evaluation-table.md` §3, §5.
- **Outcome**: ADR-002. **Confidence**: medium-high; EODHD HK coverage unverified empirically (risk R-02).
- **Would change the assessment**: coverage report below threshold; brokerage account acquisition.

### Q-03 — Storage: SQLite + sqlite-vec
- **Date**: 2026-09-15 · **Question**: structured store and vector store?
- **Evidence used**: single-file operations preference (owner), corpus scale estimate (≤ ~500k vectors over 2y retention), dependency policy; `evaluation-table.md` §4, §6.
- **Outcome**: ADR-003. **Confidence**: high on operations; medium on sqlite-vec maturity (risk R-01).
- **Would change the assessment**: KNN latency at scale; extension portability break.

### Q-04 — Context engineering parameters
- **Date**: 2026-09-15 · **Question**: layer structure, budgets, compaction threshold, model routing?
- **Evidence used**: course D2.2 requirements, INV-001 long-session integrity (provenance ledger non-compactable), owner decisions (80% threshold default, `deepseek-v4.1-flash` all roles).
- **Outcome**: ADR-001 §6. **Confidence**: medium — parameters are reasoned defaults, not measured.
- **Would change the assessment**: first E-entries on token usage and post-check behavior in long sessions.

## E-entries (empirical) — to be appended

Template for future entries:

```
### E-NNN — <title>
Date: ... · Prompt version: ... · Model(s): ... · Profile: ...
Scores: faithfulness = ... (threshold 0.6, QA-001) · relevance@5 = ... (0.8, QA-002)
Verdict: pass / blocked (gate) · Notes / anomalies ...
```

Rules: every prompt or model change gets an E-entry before production (GOV-003); failed thresholds record a diagnosis and the follow-up decision; E-entries are append-only.

### E-001 — First evaluation-set replay (seed harness landing)
Date: 2026-09-16 · Prompt version: n/a (no prompts/ yet — seed-level harness) · Model(s): deepseek-v4.1-flash (chat role; endpoint via PROVIDER_BASE_URL secret) · Profile: n/a
Scores: faithfulness(seed) = 6/6 = 1.00 (threshold 0.6, QA-001) · usage interface verified on live call (prompt/completion tokens returned)
Verdict: pass · Notes: per-case report emitted by the gate (CI run 35054084367): exact-echo / json-only / english-only / short-confirmation clean; yes-no format-stable across both runs but semantically inconsistent between runs ('No' vs 'yes') — the case checks format stability only; semantic determinism is deliberately out of scope for the seed set. Report-level RAG replay (QA-001 full semantics) extends the set when the agent analysis loop lands.

### E-002 — First loop-level replay: identity-v1 behavioral coverage begins
Date: 2026-09-17 · Prompt version: identity-v1 · Model(s): deepseek-v4.1-flash (chat role; full TurnEngine pipeline: streaming, tool loop, guardrail) · Profile: quick
Scores: seed set 6/6 = 1.00 (threshold 0.6, QA-001); loop-level: numbers-cited-or-degraded PASS (model called budget.query, answered "30,000 tokens" — thousands-separator normalized by the post-check, cited number verified against the snapshot); epistemic cleanliness PASS (displayed text for "Will Tencent stock rise next month?" contains zero unlabeled violations end-to-end) · verdict: pass
Verdict: pass · Notes: three real findings this round, exactly what live evaluation exists for: (1) the eval trigger did not fire for test/live/ changes — trigger now covers them; (2) OpenAI rejects dot-bearing function names — the registry now translates wire names (dots → underscores) with reverse mapping in the loop; (3) the numbers case proved the guardrail right and the test assertion too literal (comma formatting) — the test now normalizes. CI run 35184274118.

### Note (2026-09-17) — model-name correction affecting E-001/E-002 metadata

The E-001/E-002 entries above record `deepseek-v4.1-flash` as the model
in use. The live catalog exposes `deepseek-flash` (the v4.1-suffixed
name is rejected with HTTP 400), so those replays effectively ran the
endpoint's accepted model under the rejected-name default only where a
PROVIDER_CHAT_MODEL override existed; where the default was used, calls
would have failed. Defaults are corrected to `deepseek-flash` from this
date (AILOG-0023); the historical entries stand as written.

### E-003 — BD-012 display-rounding amendment (retrospective record)
Date: 2026-09-21 (recorded 2026-09-29) · Prompt version: identity v2->v3 (the version field itself was not bumped at the time — corrected in E-005) · Model(s): deepseek-flash
Scores: adversarial suite for the bounded display-rounding allowance: all pass (2-4 decimal renderings accepted within half-ulp; out-of-window renderings and fabricated values fail); live case: the 24,879.24 citation quarantined pre-fix, passed post-fix.
Verdict: pass · Notes: recorded retrospectively during the remediation round (review finding 5): the identity behavioral change shipped with ADR-006 Amendment 1 but without an evaluation-log entry at the time.

### E-004 — BD-015 marker-gated percent amendment (retrospective record)
Date: 2026-09-25 (recorded 2026-09-29) · Prompt version: identity v3->v4 content (field not bumped at the time — corrected in E-005) · Model(s): deepseek-flash
Scores: adversarial suite: percent-adjacent-marker conversions pass within half-ulp; bare numbers never qualify; +-1 classes unchanged; `101 percent` negative pinned. Live case: the 0.18573119602909305 -> "about 18.57%" citation quarantined pre-fix, passed post-fix.
Verdict: pass · Notes: recorded retrospectively (review finding 5).

### E-005 — identity v4 consolidation + live simulation battery (INV-002 record)
Date: 2026-09-29 · Prompt version: identity v4 (field corrected) · Model(s): deepseek-flash · Profile: standard
Scores: live 13-turn user-simulation battery (quotes/indicators/news/fundamentals/compare + adversarial): pre-BD-019 post-check pass rate 4/10 data-bearing turns; post-BD-019 7/10 with the three residual failures fully attributed to the recorded extraction-semantics classes (prose years, integer percents, window words, time-of-day renderings) — enumerated for the standing owner decision. Injection refusal: 1/1; INV-002 price-prediction refusal: 1/1; INV-004 agent-path confirmation: 1/1. News-filter S2 offline fixture: precision 0.927 / recall 1.000 (200 hand-labeled items).
Verdict: pass with recorded residual classes · Notes: this entry is the honest baseline for QA-001 faithfulness work (TP-017): the seed set covers format stability; numeric-provenance pass rate over live conversations is the richer measure and now has a recorded number.

### E-006 — Guardrail faithfulness measured on a labeled suite (QA-001/INV-002 record)
Date: 2026-09-29 · Prompt version: identity v4 · Model(s): n/a (unit-level: the post-check is the system under evaluation)
Scores: precision 7/7 = 1.00 and recall 6/6 = 1.00 on the labeled suite (test/offline/test_faithfulness_eval.py): good citations (exact, two-tool, in-window display rounding, marker-gated percent, ISO/compact dates, volume) all pass; fabrications (wrong decimals, off-by-one class, wrong dates, markerless percents, invented numbers) all quarantine. The four known residual classes (prose years, integer percents, window words, time-of-day renderings) still quarantine and are pinned by name in the suite - they move to the passing set only when the owner extraction-semantics decision lands (never silently).
Verdict: pass with residuals pinned · Notes: this is the honest QA-001 answer to review finding 6: the live eval seed set covers format stability (its degrade-tolerant numbers case now fails loudly instead of silently passing on degradation), while numeric-provenance faithfulness is measured where it is deterministic - at the checker, on labels. Live faithfulness remains recorded per-conversation (E-005: 7/10 post-BD-019 with residuals attributed).

### E-007 — INV-002 filter precision/recall + the audit battery as a live set
Date: 2026-09-29 · Prompt version: identity v5 · Model(s): n/a (filter: unit-level; battery: deepseek-flash, gated)
Scores: INV-002 labeled suite (10 violating / 10 clean): precision 1.00, recall 1.00 (test/offline/test_inv2_eval.py - deterministic, CI-blocking). Live battery: the six-turn audit conversation shape is now a replayable set (test/live/test_battery_simulation.py, EVAL_SET=1); outcomes print per turn for this logbook rather than asserting a pass, because model prose is non-deterministic while the filter is.
Verdict: pass · Notes: after TP-017 PR-3a the battery's historical failure classes (restated numbers, stock codes, heading ordinals) are structurally covered; the count-class ("2 symbols") remains strictly quarantined by design (owner decision record, PR-016 epsilon / TP-017 PR-3a).

### E-007a — INV-002 adversarial battery, author-separated (TP-018)

Date: 2026-09-29 - Prompt version: identity v5 - Model(s): n/a (filter, unit-level)
Scores: battery DERIVED FROM the third review's reported violation classes
(10 violating / 4 reported-speech; adapted by the remediation author, NOT
verbatim auditor sentences - an auditor-authored held-out set remains the
reviewer's instrument; fourth-audit honesty correction): precision 1.00,
recall 1.00
(test/offline/test_tp018_remediation.py, CI-blocking). The original
same-author labeled suite (20 sentences) remains green at P=1.00/R=1.00;
the new battery additionally pins the reported-speech exemption (4/4 pass)
and the modal-certainty classes the audit showed slipping (10/10 caught).
Verdict: pass - Notes: M3 measured on an author-separated set as the third
audit required; regex recall remains inherently bounded - new violation
classes beyond the pattern families are a documented limitation
(ADR-006 Am6), with the phase-2 direction recorded there.


### E-007b — INV-002 fourth-audit battery (narrowed attribution + modal recall)

Date: 2026-09-29 - Model(s): n/a (filter, unit-level)
Scores: adapted battery (9 directional: 5 laundering/prediction must-fail,
4 true reported speech must-pass): 9/9 correct
(test/offline/test_tp018b_fourth_audit.py, CI-blocking). The auditor's own
held-out sentences (11 + 10 from the fourth report) remain unmeasured here -
the reviewer must run them; local recall on their REPORTED classes improved
(4/11 -> covered classes for chart-analysis attribution, expected/predicted/
projected reach/exceed/double, modal set) but the full held-out number is
theirs to publish.
Verdict: pass (bounded) - Notes: regex recall stays inherently bounded;
phase-2 direction and known open classes recorded in ADR-006 Am7.


### E-008 — INV-002 fifth-audit batteries + live precision sanity (TP-019)

Date: 2026-09-30 - Model(s): n/a (filter, unit-level); live sanity on deepseek-flash
Scores: fifth-review sentence sets, measured after TP-019 - original audit
set 11/12 violating caught (0/1 clean flagged); fresh set 10/10 (0/5);
laundering + cross-clause hedge set 10/10 (0/1). Total 31/32 caught, 0/7
clean flagged. Regression batteries unchanged: E-007 10/10 caught, 0/10
flagged; E-007a/b and the TP-018/TP-018b attribution tests green. Live
precision sanity: 12 post-check-passing assistant answers from the
post-fix live run - 0 sentences flagged.
Verdict: pass (bounded) - Notes: HONESTY - the same agent that received
these sentences in the review tuned the TP-019 patterns against them, so
they are now a DEVELOPMENT set; the numbers are not independent held-out
evidence (DE-09). The one miss is the recorded residual class (a hedge
governing another verb in the same clause: "We could see that the price
will rise sharply"). A freshly authored held-out set, written by someone
other than the pattern author, is the next measurement.

### E-009 — INV-001 partial-date semantics (TP-020)

Date: 2026-10-01 - Model(s): n/a (checker, unit-level); live trigger on deepseek-flash
Scores: TP-020 labeled cases (test/offline/test_tp020_partial_dates.py) -
correctly cited partial dates (month-years, ISO year-months, framed bare
years, framed ranges, the live BYD shape end to end): 25/25 pass;
fabricated or unsupported references (absent months and years, a wrong
day, values equal to an evidence year in value frames, numbers shaped
like months): 21/21 quarantined, 0 escapes; fail-closed residual pins
(unframed years): 2/2 still quarantine. The E-006 suite is unchanged:
precision 7/7, recall 6/6, and its "prose year" residual ("between
October 2025 and June 2026") still quarantines - correctly, since
neither month is in that suite's evidence.
Verdict: pass - Notes: the "prose years" class of E-005/E-006 moves to
the passing set where the evidence supports the date, by owner decision
(2026-10-01: bare years allowed); the remaining partial-date residuals
are DE-13. Not yet re-measured live: the next live session should
replay the BYD question.

### E-010 — INV-001 typed claims (TP-024)

Date: 2026-10-02 - Model(s): n/a (checker, unit-level)

Corpora:
- test/offline/fixtures/e010_dev.yaml: 48 answers, 82 labeled claims,
  written with the engine.
- test/offline/fixtures/e010_heldout.yaml: 51 answers, 250 claims
  (170 correct, 80 wrong). Written by a separately briefed agent session
  and committed before any engine code. Labels pending owner review.

Scores:
- Development set: precision 61/61, recall 21/21, no flags on unlabeled
  numbers.
- Held-out set, first run on the frozen engine: precision 156/170 =
  0.918, recall 68/80 = 0.850.
- Held-out set after the refinements of TP-024 Amendment 1 (each pinned
  by a development item): precision 168/170 = 0.988, recall 75/80 =
  0.938.
  - The 5 escapes are the company-name class (DE-16), waived by the
    owner for TP-024.
  - The 2 false flags are pinned residuals: the field was stated in the
    previous sentence.
- ADR-008 probe: 4/4 correct renderings verify; 4/4 misattributions are
  flagged, each with its reason; the DE-12 table swap is flagged.
- E-006 suite: GOOD 9/9 pass, BAD 6/6 flagged. Residuals: prose year,
  window word, time of day.
- Mutation evidence: against the pre-change tree 36/55 new cases fail;
  10 injected mutations are each caught.

Verdict: pass, with one class waived.

Notes:
- The post-fix held-out numbers are not an independent measurement for
  the refined classes; a fresh held-out set is the next evaluation's
  instrument.
- Not yet measured live: replay the BYD question after merge.

### E-011 — QA-002 retrieval relevance on frozen real vectors (TP-036)

Date: 2026-10-26 - Model(s): qwen3.7-text-embedding-flash (embedding role, 1024 dims; vectors frozen once by test/live/gen_retrieval_vectors.py)

Corpus and queries:
- test/offline/fixtures/news_corpus_v1.json, the 89 keep-labeled titles
  (the D1 title corpus).
- test/offline/fixtures/retrieval_queries_v1.json: 25 known-target
  queries in five classes (official name, ticker, alias, macro,
  paraphrase); relevance judged by 12 topic families that partition
  the corpus. Families and targets were fixed before this measurement.

Scores (k = 5, no bucket filter, production knn path):
- hit@5 = 23/25 = 0.920 (FR-007 fit criterion, gate 0.8): pass.
- relevance@5 = 0.768 (QA-002, gate 0.8): miss by 0.032.
- Ceiling: the hk_rates and trade families hold 2 items each, so two
  queries cap at 0.4; the best reachable mean is 0.952.
- Weak queries: q14 alias "WeChat commerce growth" 0.2 (no link from
  WeChat to Tencent); q20 macro "Hong Kong interbank rates" misses its
  target (HK index headlines rank first); q18, q23, q24 at 0.4 (target
  found, the rest of the top 5 from other families). Official-name and
  ticker queries q02-q13 score 1.0.
- Controls: reversed ranking and random query vectors fail both gates.

Verdict: blocked (gate). hit@5 passes; relevance@5 misses. Owner
decision (2026-10-26): land the suite with the relevance assertion as
a strict expected failure (DE-17), and try a retrieval improvement
under its own plan (TP-037). The D1 v2 precondition stays unmet, so
TP-035 stays blocked.

### E-012 — Retrieval variants on a held-out query set (TP-037 stage 1)

Date: 2026-10-26 - Model(s): qwen3.7-text-embedding-flash (1024 dims; corpus vectors from E-011, query vectors frozen once per variant)

Sets:
- Development: the 25 TP-036 queries (looked at in E-011).
- Held-out: 25 queries written by a separately briefed subagent from the
  corpus, the family partition, the classes and the labeling rule
  only; committed before any variant vector. Two queries match
  development text exactly (held-out 11, 17); the 23-query subset
  without them is reported alongside.

Variants (fixed in TP-037 before measurement): V0 baseline; V1
retrieval instruction prefix on queries; V2 production-shaped entity
expansion (ticker / official-name head / index alias -> "<official
name> (<code>)"); V3 = V1 on V2.

Scores (k = 5; relevance@5 / hit@5):

| Variant | Development | Held-out | Held-out (23) |
|---|---|---|---|
| V0 | 0.768 / 0.920 | 0.720 / 1.000 | 0.748 / 1.000 |
| V1 | 0.776 / 0.920 | 0.712 / 1.000 | 0.730 / 1.000 |
| V2 | 0.768 / 0.960 | 0.736 / 1.000 | 0.765 / 1.000 |
| V3 | 0.784 / 0.960 | 0.728 / 1.000 | 0.748 / 1.000 |

Per class on the held-out set (V0 -> best variant): official name
0.96 -> 1.00 (V2), ticker 1.00 throughout, alias 0.52 -> 0.56,
macro 0.56 throughout, paraphrase 0.56 throughout. The macro class is
capped at 0.76 by its families (two of five macro queries aim at
2-item families); the set's reachable mean is 0.952.

Verdict: blocked (gate). No variant reaches relevance@5 0.8 on the
held-out set; the best, V2, gains 0.016. V3 leads on the development
set but not on the held-out set, so the development gain does not
transfer. hit@5 passes for every variant. The gap is in alias,
paraphrase and macro queries, which query-side changes do not reach:
the top 5 is filled with headlines from neighbouring families. Owner
decision pending (TP-037 stage 2).

### E-013 — Phase-3 typed claims, independent held-out remeasurement (TP-025 stage 5)

Date: 2026-10-27 - Model(s): n/a (checker, unit-level)

Instrument:
- test/offline/fixtures/e013_ledgers.yaml: five session ledgers produced by
  the real tools over a seeded store (stage-3 declarations and stage-4 names
  in place); a drift test rebuilds them.
- test/offline/fixtures/e013_heldout.yaml: 53 answers, 162 claims (109
  correct, 53 wrong). Written by a separately briefed subagent from the
  frozen ledgers and the brief only (e013_brief.md), committed unedited
  before the run.
- Label check without the engine: 9 disagreements, all checker limits; the
  owner ruled that every label stands, and accepted the author's rule for
  unverified names (labeled by value).
- Engine frozen at the stage-4 tree (blob hashes: guardrail_claims.py
  7351368, guardrail.py 615d8f1, registry.py fd202ad). Run once, on the
  production path (post-check with the declared tool specs).

Scores:
- Precision 89/109 = 0.817; recall 48/53 = 0.906; no flags on unlabeled
  numbers.
- Per class (false flags / correct; escapes / wrong): name misattribution
  2/9, 0/9; subject after the number 4/10, 2/5; company absent from the
  ledger 0/4, 1/6; unverified name 0/9, 0/5; common-word name 1/6, 0/3;
  tables 9/25, 0/6; general 4/46, 2/19.

Causes:
- False flags (20): the subject written after its number, "6.35% for
  Target" (4); "revenue grew X% year on year" typed as revenue, because
  "year on year" is not a growth cue (5); the company name "Target" as a
  table row label read as the price-target cue (6); a scale stated in a
  table title, "(USD billions)" (3); a cue reaching the next number, and
  total assets having no field class (2).
- Escapes (5): the subject written after its number (2); a company absent
  from the ledger (1); which list item a value belongs to, an article's
  sentiment share or a search result's distance (2).

Verdict: measured, no threshold set in advance (owner decision). Precision
is below the 0.90 that E-010 required. Recall is 0.906 on a battery that
targets the hard classes. Name misattribution and unverified names, the
classes stages 3-4 address, are clean. Escapes and false flags are pinned
by name in test/offline/test_tp025_stage5_e013.py. Follow-ups are an
owner decision.

### E-014 — Growth phrasing and the name/cue collision (TP-039)

Date: 2026-10-27 - Model(s): n/a (checker, unit-level)

Instrument: test/offline/fixtures/e014_heldout.yaml, 50 answers, 127
claims (93 correct, 34 wrong), written by a separately briefed subagent
from the frozen E-013 ledgers and e014_brief.md only, committed unedited
before the rule code. Label check: 8 disagreements, all checker limits;
the owner ruled that every label stands.

Scores (production post-check path, declared specs):

| Engine | Precision | Recall |
|---|---|---|
| Before TP-039 | 66/93 = 0.710 | 34/34 |
| TP-039, first run (independent) | 76/93 = 0.817 | 34/34 |
| TP-039 after the F012 fix (not independent for F012) | 77/93 = 0.828 | 34/34 |

Per class, false flags before -> after the fix: growth phrasing 11 -> 2
(of 15 correct); name/cue collision 10 -> 8 (of 26; 7 are the
table-title scale); general 6 -> 6 (of 52). No escapes in any run.

Development set E-013 after TP-039: precision 97/109 = 0.890 (from
0.817), recall unchanged at 48/53.

Verdict: improvement measured on a battery the rules were not tuned on.
The one regression the first run exposed (F012) is fixed and disclosed.
Remaining: growth vocabulary ("top line expanded", "sales growth"), a
scale stated in a table title (option c), a subject written after its
number (option d), and pinned singletons.
