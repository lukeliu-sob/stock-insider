# Trace Matrix — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/architecture/trace-matrix.md` (course deliverable D2.4) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Registry baseline | `docs/req/requirements.yaml` v0.3.2 (47 entries) |
| Related | `architecture-blueprint.md` §5 (components), §11 (observability) |

Mapping: **every requirement → enforcing component → test/evidence → runtime monitor**.

**Monitor legend** (blueprint §11 streams): S1 session records · S2 tool-call log · S3 post-check verdicts · S4 usage accounting · S5 sync/gap reports. `—` means no runtime monitor (verified statically or by CI gate only).

## Functional requirements

| Req | Component(s) | Test / evidence | Monitor |
|---|---|---|---|
| FR-001 EOD ingestion | `data/ingest`, `cli` (`sync`) | `test/offline/test_ingest_market.py` | S5 |
| FR-002 Fundamentals ingestion | `data/ingest` (EODHD adapter, ADR-002) | `test/offline/test_ingest_fundamentals.py` | S5, coverage report |
| FR-003 News ingestion | `data/ingest` (GDELT adapter + crawler, ADR-002) | `test/offline/test_ingest_news.py` | S5 |
| FR-004 Watchlist management | `data/store`, `agent/registry` (SymbolResolver gate) | `test/offline/test_watchlist.py` | watchlist audit log |
| FR-005 Basic info display | `cli` (`info`), `data/store` | `test/offline/test_cli_info.py` | — |
| FR-006 Deterministic computation | `data/compute` + CI static gate | `test/offline/test_indicators.py` | — |
| FR-007 RAG retrieval | `data/store` (sqlite-vec, ADR-003) | `test/offline/test_retrieval.py` | retrieval precision log (QA-002) |
| FR-008 Analysis report | `agent/context`, `agent/guardrail`, pipeline | `test/offline/test_agent_loop.py`, `test/offline/test_report_gate.py`, `test/live/test_eval_set.py` | S3 |
| FR-009 Event scoring | `agent/providers` (chat + JSON schema), `data/store` (`events`) | `test/offline/test_event_scoring.py` | S1 (model/prompt stamps on events) |
| FR-010 Event study | `data/compute` | `test/offline/test_event_study.py` | — |
| FR-011 Session persistence | `agent/session` | `test/offline/test_session_persistence.py` | S1 (index integrity) |
| FR-012 Sessions listing | `cli` (`sessions`) | `test/offline/test_cli_sessions.py` | — |
| FR-013 Hybrid CLI | `cli`, `agent/repl` | `test/offline/test_cli_surface.py` | — |
| FR-014 English-only output | `shared` (language check), all render paths | `test/offline/test_language_policy.py` | — |
| FR-015 Whitelist crawler | `data/ingest` (crawler) | `test/offline/test_crawler.py` | S2 (fetch log) |
| FR-016 Weekly digest | `cli` (`digest`), `data/compute`, `agent/guardrail` | `test/offline/test_weekly_digest.py` | S1 |
| FR-017 Currency display toggle | `cli`, `data/store` (FX series) | `test/offline/test_currency_display.py` | — |
| FR-018 Full-market sync | `data/ingest` (bulk mode) | `test/offline/test_bulk_sync.py` | S5 |
| FR-019 Streaming output | `agent/repl`, `agent/providers` | `test/offline/test_streaming.py` | S1 (stream markers/timestamps) |
| FR-020 Analysis profiles | `agent/context`, `agent/session` | `test/offline/test_profiles.py` | S1 (profile field) |
| FR-021 Provider config | `agent/providers` | `test/offline/test_provider_config.py` | S1 (provider stamps) |
| FR-022 Session review (show) | `cli` (`show`), `agent/session` | `test/offline/test_show.py` | — |
| FR-023 Session resume | `agent/session` | `test/offline/test_resume.py` | S1 (status transitions) |
| FR-024 Chinese news pipeline | `data/ingest` (deferred, FR-024 Could) | `test/offline/test_zh_news.py` (planned) | — |
| FR-025 Quant models | `data/quant` (deferred, future) | none until ADR reopen (per fit criterion) | — |

## Invariants

| Req | Component(s) | Test / evidence | Monitor |
|---|---|---|---|
| INV-001 Numeric provenance | `agent/guardrail` (+ `agent/session` snapshots, `agent/context` provenance ledger) | `test/offline/test_inv1_postcheck.py` (adversarial, 0-escape) | S3 |
| INV-002 Epistemic safety | `agent/guardrail` | `test/offline/test_inv2_filter.py` + eval replay | S3 |
| INV-003 Fail-safe | `data/ingest`, `agent/registry`, `agent/providers` | `test/offline/test_inv3_failsafe.py` (fault injection) | S2, S5 |
| INV-004 Symbol resolution gate | `data/store` (SymbolResolver), `agent/registry` write gate | `test/offline/test_inv4_symbol_gate.py` (adversarial) | watchlist audit log |

Operational fallbacks for all four: `invariants.md` (per-invariant concrete actions).

## Quality attributes

| Req | Component(s) | Test / evidence | Monitor |
|---|---|---|---|
| QA-001 Faithfulness ≥ 0.6 | agent pipeline + eval harness | `test/live/test_eval_set.py` (semantic evaluation gate) | eval gate records (CI artifact) |
| QA-002 Retrieval relevance@5 ≥ 0.8 | `data/store` (retrieval) | `test/offline/test_retrieval.py` | retrieval precision log |
| QA-003 Data completeness ≥ 0.99 | `data/ingest` self-check | `test/offline/test_ingest_market.py` | S5 |
| QA-004 Citation coverage = 1.0 | `agent/guardrail` | `test/offline/test_report_gate.py` | S3 |

## Performance (deferred, status: future)

| Req | Component(s) | Test / evidence | Monitor |
|---|---|---|---|
| PERF-001 Basic-info latency | unassigned (deferred by owner decision R4 item 4) | timing mode of `test_cli_info.py`, once thresholds set | — |
| PERF-002 Analysis session duration | unassigned (deferred by owner decision R4 item 4) | timing mode of `test_eval_set.py`, once thresholds set | — |
| PERF-003 Sync throughput | unassigned (deferred by owner decision R4 item 4) | timing mode of `test_ingest_market.py`, once thresholds set | — |

## Cost

| Req | Component(s) | Test / evidence | Monitor |
|---|---|---|---|
| COST-001 Tiered budgets + overflow | `agent/context` (budget enforcement, ADR-001 §6.3) | `test/offline/test_budget_overflow.py` | S4 |
| COST-002 Usage logging | `agent/providers` | `test/offline/test_session_persistence.py` | S4 |

## Governance

| Req | Component(s) | Test / evidence | Monitor |
|---|---|---|---|
| GOV-001 English-only policy | `shared`, all artifacts and output paths | `test/offline/test_language_policy.py` | — |
| GOV-002 AI-use log gate | CI workflow | `.github/workflows/ci.yml` gate test | CI gate results |
| GOV-003 Prompt versioning | `prompts/`, `agent/providers` (version stamps) | CI eval-gate test | S1 (prompt version per session) |
| GOV-004 Watchlist cap | `data/store` | `test/offline/test_watchlist.py` | watchlist audit log |
| GOV-005 Session provenance stamps | `agent/session`, `agent/providers` | `test/offline/test_session_persistence.py` | S1 |
| GOV-006 Test approval gate | CI workflow + `docs/test-plans/` | `tools/checks/testplan_gate.py` gate test | CI gate results |

## Security

| Req | Component(s) | Test / evidence | Monitor |
|---|---|---|---|
| SEC-001 Secrets hygiene | repo hygiene, CI secret scan | CI scan job | CI scan results |
| SEC-002 Untrusted-input defense | `agent/context` (sanitize), `agent/registry` (schemas), `agent/guardrail` (policy) | `test/offline/test_injection_suite.py` | S2 (tool-call anomalies), S3 |
| SEC-003 Egress whitelist | `shared` (HTTP choke point) | `test/offline/test_egress.py` | S2 (egress denials) |

## Matrix discipline

- Coverage rule (blueprint §13): every Must requirement maps to ≥ 1 component; every component maps to ≥ 1 requirement. A requirement without a component is an unkept promise; a component without a requirement is deletion debt.
- Deferred rows (FR-024, FR-025, PERF-001..003) are tracked traceability debt: activating them requires their registry `notes`/ADR reopen conditions first, then this matrix row is completed in the same change set.
- This matrix is regenerated-checked by CI (structural gate): requirement IDs in this file must exactly cover the registry's current entry set.
