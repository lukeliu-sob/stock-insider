# Risk List — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/architecture/risk-list.md` (course deliverable D2.10, optional — maintained) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Related | ADR-001/002/003; `evaluation-logbook.md`; `docs/debt-register.md` |

Assumptions that could become defects, each with a review trigger. A risk without a trigger is unmanaged; a triggered risk must open a bug-diary or debt entry.

| ID | Assumption | Becomes a defect if... | Review trigger | Mitigation on record |
|---|---|---|---|---|
| R-01 | sqlite-vec remains portable and stable on target platforms | extension fails to load or KNN results drift | KNN-path regression fails; platform portability break | pinned version + KNN regression test (ADR-003) |
| R-02 | EODHD HK fundamentals meet the 99% field-completeness criterion | coverage report falls below threshold on any watchlist symbol | coverage report < 99% on required fields | adapter swap path (ADR-002 reopen) |
| R-03 | DeepSeek exposes a usable embedding endpoint for the default model | implementation-time verification fails | first provider integration test | config fallback to separate embedding provider (ADR-001 §6.5) |
| R-04 | Brute-force KNN suffices at corpus scale | retrieval latency degrades or QA-002 misses accumulate | sustained retrieval latency complaints; relevance@5 < 0.8 | ADR-003 reopen conditions |
| R-05 | The LLM does not perform arithmetic outside tools | model narrates computed-sounding numbers not in context | static arithmetic gate or INV-001 post-check findings | FR-006 structural gate + post-check |
| R-06 | Prompt quality does not drift unnoticed | faithfulness decays below threshold without an alarm | semantic evaluation gate score trend (QA-001) | GOV-003 versioning + eval gate |
| R-07 | Injection neutralization covers new payload shapes | adversarial corpus evolves past sanitization | injection-suite failures; tool-call anomalies (S2) | SEC-002 three-layer defense; suite maintained |
| R-08 | Terminology stays single-meaning across authors | future edits reintroduce polysemous terms | language/term checks in CI | glossary rules (D1) |
| R-09 | Backfill + sync concurrency stays within rate limits | sustained 429s during watchlist expansion | sync reports show sustained throttling | P-02 escalation; tier upgrade path (ADR-002) |
| R-10 | Session format evolution stays backward-compatible | `show`/`resume` of older-format sessions fails | compatibility test on format bump | format-version field + compatibility tests (memory-design §4) |
| R-11 | Single-provider concentration is acceptable | provider outage disables sessions entirely | provider downtime incidents | FR-021 configurable providers (swap without code change) |
| R-12 | Unbounded session accumulation is tolerable | `sessions/` growth impedes operation | disk monitoring threshold | archive path (owner action); values-as-seen snapshots are the audit basis and are not auto-pruned |
