# Runtime Policy Catalog — Stock Insider

| Field | Value |
|---|---|
| Document | `docs/architecture/runtime-policy-catalog.md` (course deliverable D2.7) |
| Version | 0.1.0 |
| Date | 2026-09-15 |
| Registry baseline | `docs/req/requirements.yaml` v0.3.1 |
| Related | `invariants.md` (authoritative fallbacks); ADR-001/002/003; `memory-design.md` |

What the system does when each degraded or failure path is triggered. Invariant fallbacks remain normative in `invariants.md`; this catalog consolidates all runtime paths in one place. Format: **trigger → immediate behavior → user-visible outcome → escalation / recovery → source**.

## A. Data path

| # | Trigger | Immediate behavior | User-visible outcome | Escalation / recovery | Source |
|---|---|---|---|---|---|
| P-01 | Data gap detected (calendar vs stored bars) | Auto-backfill on next `sync` | Gap listed in sync output | Gap persisting > 2 sync cycles is flagged for manual review | FR-001, QA-003 |
| P-02 | Ingestion API failure / sustained rate limit | Transactional abort for that source; no partial writes | Sync report names the failure | Retry next sync; sustained EODHD throttling → **human action: tier upgrade** (ADR-002) | FR-002/003, INV-003 |
| P-03 | Stale data requested (market open / gap present) | Freshness labels from exchange calendar | Every numeric renders with "as of \<date\>" | — | FR-005, INV-003 |
| P-04 | Vector index missing / embedding-model mismatch | Deterministic rebuild from news corpus with the configured model; retrieval fails explicitly during rebuild | "Retrieval unavailable: rebuilding" | Completion notice. **No keyword fallback** — silent quality degradation is forbidden | ADR-003, FR-007 |

## B. Model / turn path

| # | Trigger | Immediate behavior | User-visible outcome | Escalation / recovery | Source |
|---|---|---|---|---|---|
| P-05 | Provider failure / stream interruption mid-response | Abort turn; partial usage recorded; no fabricated completion | Explicit error; session resumable | `resume` continues from last complete turn | INV-003 |
| P-06 | Malformed model output (schema-invalid score etc.) | Reject and log; never silently repaired | News item marked unscored | Eligible for the next scoring pass | FR-009, INV-003 |
| P-07 | INV-001 post-check failure | Quarantine response (stored, flagged `post_check: failed`, never displayed) | Degraded "data unavailable for: \<numerics\>" | 3 consecutive failures → session abort + bug-diary entry | INV-001 |
| P-08 | INV-002 violation | Strip passage; one constrained regeneration | Labeled refusal if regeneration still violates | > 2 per session → session abort + evaluation-logbook entry | INV-002 |
| P-09 | Injection payload detected in untrusted content | Neutralize; log to tool-call and verdict streams; tool selection unchanged | Excluded content noted in the turn if neutralization is uncertain | Repeated payloads from one source → source/crawler review | SEC-002 |

## C. Resource and boundary path

| # | Trigger | Immediate behavior | User-visible outcome | Escalation / recovery | Source |
|---|---|---|---|---|---|
| P-10 | Context reaches 80% of profile budget (default threshold, configurable) | Compact L4 → L5 with mandatory re-injection (invariants, provenance ledger, symbols, task) | Compaction notice in stream | `/compact` available anytime | ADR-001 §6.3 |
| P-11 | Budget overflow after compact-and-retry | Explicit budget-exceeded abort | Clear report | New session or higher-tier profile | COST-001 |
| P-12 | Symbol resolver unavailable | `watchlist_add` disabled | Explicit notice; all other features unaffected | Restored when the endpoint returns | INV-004 |
| P-13 | Watchlist cap reached (100) | Addition rejected | Explicit error suggesting removal first | — | GOV-004 |
| P-14 | Egress attempt to non-whitelisted host | Blocked at the choke point | Error report | Logged; unexpected attempts investigated | SEC-003 |

## D. Storage and session path

| # | Trigger | Immediate behavior | User-visible outcome | Escalation / recovery | Source |
|---|---|---|---|---|---|
| P-15 | DB locked / corruption | Busy-timeout, then explicit error | Error surfaced | Single-file restore from backup artifact (ADR-003) | ADR-003 |
| P-16 | Session file corruption | That session marked unreadable | `show`/`sessions` handle it explicitly | Folder quarantined; other sessions unaffected | FR-011 |
| P-17 | Mid-turn crash (interruption) | Partial turn marked `incomplete` | — (invisible until resume) | `resume` continues from the last complete turn; incomplete turns excluded from context | memory-design §3 |

## E. CI-time policies (reference only — detailed in D4)

Test-approval gate (D7-1) · static analysis gates (D7-2) · schema gate (D7-3) · semantic evaluation gate (D7-4) · regression gate (D7-5) · AI-use log gate (D7-6). Implemented in `.github/workflows/ci.yml` under verification governance (`docs/code-governance/verification-constraints.md`).

## Discipline

- Every policy row must map to at least one test path (fail-safe suite, post-check suite, budget suite, egress suite); a policy without a test is debt.
- Adding or changing a policy is a registry/architecture change: it follows the change policy (blueprint §12) and updates this catalog in the same change set.
