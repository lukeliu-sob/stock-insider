# Invariant Register — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/architecture/invariants.md` (course deliverable D2.3) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Registry baseline | `docs/req/requirements.yaml` v0.3.1 |
| Related | `architecture-blueprint.md` §6; ADR-001; `trace-matrix.md` |

The requirement registry (`REQ-SI-INV-001..004`) is the normative source for invariant statements; this register is the architecture-side elaboration: enforcing components, verification design, and **operational fallbacks** — concrete actions the system takes when an invariant is violated at runtime. "Fix the bug" is a maintenance activity, not a fallback; every fallback below is something the running system does.

## Summary

| ID | Rule (one line) | Enforcing component | Runtime fallback (short) |
|---|---|---|---|
| INV-001 | Every numeric in output traces to a snapshot-registered record | `agent/guardrail` | Quarantine response; degrade to explicit data-unavailable statement |
| INV-002 | No deterministic causal claims or price predictions | `agent/guardrail` | Strip + one constrained regeneration; else degrade to labeled refusal |
| INV-003 | Failures reported explicitly; never substituted values | `data/ingest`, `agent/registry`, `agent/providers` | Per-failure-point explicit failure reports (below) |
| INV-004 | Watchlist additions only via verified resolution + confirmation | `data/store` (SymbolResolver), `agent/registry` | Reject addition with explicit report; disable additions if resolver down |

---

## INV-001 — Numeric provenance

- **Statement**: every numeric value in agent output must trace to a database record or computed result registered in the response's context snapshot; a deterministic post-check verifies each numeric against that snapshot; on mismatch the response degrades to an explicit data-unavailable statement (registry `REQ-SI-INV-001`). Match semantics (BD-012): exact after normalization, plus a bounded display-rounding allowance — a token with exactly 2–4 decimals matches a pool value within half an ulp of that decimal place (tracked as `rounded` for audit); integer-scale deviations never match.
- **Source requirement**: REQ-SI-INV-001 (owner requirement R1 item 1; core anti-hallucination demand).
- **Enforcing component(s)**: `agent/guardrail` (post-check executor); supported by `agent/session` (values-as-seen snapshots, FR-011) and `agent/context` (provenance ledger, ADR-001 §6.4).
- **Verification**: `test/offline/test_inv1_postcheck.py` — adversarial suite (injected fabricated numbers rejected with 0 escapes), boundary ±1 cases (correctly cited numbers pass 100%); companion measurement QA-004.
- **Runtime detection**: post-check verdicts stream (blueprint §11).
- **Operational fallback (violated at runtime)**:
  1. The failing response is **quarantined**: stored in `session.jsonl` flagged `post_check: failed`, never displayed.
  2. The user receives the degraded statement: `data unavailable for: <list of failed numerics>`.
  3. The session continues (the user may re-pull data or re-ask).
  4. If **3 consecutive responses** fail post-check in one session, the session aborts with an explicit error (INV-003 semantics) and a bug-diary entry is opened referencing the failing numerics and the snapshot manifest.

## INV-002 — Epistemic safety

- **Statement**: agent output contains no deterministic causal claims between events and prices, no deterministic price predictions; speculative judgments carry explicit hypothesis labels (registry `REQ-SI-INV-002`).
- **Source requirement**: REQ-SI-INV-002 (owner decision R3 item 7 — compliance framing replaced by epistemic-safety framing).
- **Enforcing component(s)**: `agent/guardrail` (epistemic filter).
- **Verification**: `test/offline/test_inv2_filter.py` (adversarial prompt suite, 0 violating outputs pass the filter) + evaluation-set replay (`test/live/test_eval_set.py`); filter precision/recall recorded in the evaluation logbook.
- **Runtime detection**: post-check verdicts stream.
- **Operational fallback (violated at runtime)**:
  1. The violating passage is stripped; **one** regeneration attempt runs with a strengthened constraint reminder injected.
  2. If regeneration still violates, the response degrades to an explicit refusal plus a hypothesis-labeled summary of what could not be stated safely.
  3. More than 2 violations in one session → session aborts with explicit error; evaluation-logbook entry opened (potential prompt/model drift).

## INV-003 — Fail-safe

- **Statement**: on data gaps, provider/API failures, or validation failures, the system reports the failure explicitly and produces no substitute values — never fabricated, never stale-as-fresh, never silently estimated (registry `REQ-SI-INV-003`).
- **Source requirement**: REQ-SI-INV-003 (accepted design R2 item 4).
- **Enforcing component(s)**: `data/ingest` (schema validation, transactional writes, gap detection), `agent/registry` (fail-closed tool semantics), `agent/providers` (error propagation, no default values).
- **Verification**: `test/offline/test_inv3_failsafe.py` — fault-injection suite (API error, missing field, stale record, schema-invalid payload): 0 fabricated/substituted values; every injected fault produces a visible failure report.
- **Runtime detection**: tool-call log (S2) error entries; sync/gap reports (S5).
- **Operational fallback — per failure point**:
  - **Ingestion failure**: the gap is recorded transactionally (no partial writes); the sync report lists the failure; the next `sync` retries; stale data is never presented as current (freshness labels come from the exchange calendar).
  - **Tool failure mid-turn**: the turn continues with an explicit `tool <name> failed: <reason>` fact injected; if the failed tool was essential to the question, the turn degrades to a failure report naming the missing data.
  - **Provider failure**: the turn aborts with an explicit error; partial usage is recorded; no content is generated from defaults.
  - **Storage failure**: the session is marked `degraded` in the index; the CLI reports the condition; no silent continuation.

## INV-004 — Verified symbol resolution

- **Statement**: a security enters the watchlist only through symbol resolution verified against the provider search API with explicit user confirmation; never a guessed identifier (registry `REQ-SI-INV-004`).
- **Source requirement**: REQ-SI-INV-004 (owner decisions R4 items 1 and 3).
- **Enforcing component(s)**: `data/store` (SymbolResolver), `agent/registry` (write-gate on `watchlist_add`).
- **Verification**: `test/offline/test_inv4_symbol_gate.py` — adversarial suite (fabricated tickers, wrong-exchange collisions, partial names): 0 additions without verified resolution + confirmation.
- **Runtime detection**: watchlist audit log (mutations with resolution evidence).
- **Operational fallback (violated or unresolvable at runtime)**:
  1. An unresolved or ambiguous mention produces an explicit `not found / ambiguous candidates: <list>` message stating what was tried; nothing is added.
  2. If the resolver endpoint is unavailable, `watchlist_add` is **disabled** with an explicit notice; all other features continue unaffected.
  3. A declined or timed-out confirmation adds nothing; the mention is logged as unresolved for future ingestion planning.

---

## Register discipline

- Registry rows remain the single normative source; any conflict between this register and the registry resolves in favor of the registry, then triggers a register revision.
- Every fallback here is exercised by at least one test path (fail-safe suite, post-check suite, symbol-gate suite) — a fallback without a test is debt.
- Violations that reach users despite fallbacks are defects: each incident opens a bug-diary entry classifying which layer failed to contain it (methodology §7.2 group A/B).
