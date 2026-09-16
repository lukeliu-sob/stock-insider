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
