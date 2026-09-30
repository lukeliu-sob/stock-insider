# ADR-002 — Commercial Data Source and News Ingestion

| Field | Value |
|---|---|
| ID | ADR-002 |
| Status | Accepted |
| Date | 2026-09-15 |
| Registry baseline | `docs/req/requirements.yaml` v0.3.1 |
| Governs | `data/ingest` adapter set; FR-002 (fundamentals, Must), FR-003 (news, Must), FR-015 (crawler, Should) |
| Related | ADR-003 (storage); `evaluation-table.md` (candidate scoring) |

## 1. Decision

1. **Commercial fundamentals/quotes source: EODHD** (REST, stateless). Rate-limit handling policy: on sustained throttling, upgrade to a higher paid tier — capacity is bought, never worked around with retry storms.
2. **News ingestion: GDELT (primary; free; English; query-filtered) + the whitelist crawler (FR-015)** as the complementary path. The crawler's designed purpose includes **future Chinese-media support** (FR-024); its initial targets are English financial media.

## 2. Alternatives Considered

| Candidate | Verdict | Reason |
|---|---|---|
| Futu / Tiger OpenAPI | Rejected (reopenable) | Requires a resident gateway process (daemon-shaped dependency, contradicts blueprint §2 deployment shape); history K-line quotas; data-storage terms require case-by-case verification. |
| IBKR API | Rejected | Highest integration complexity; fragmented data subscriptions. |
| Tushare Pro | Rejected | HK fundamentals coverage insufficient at acceptable point tiers. |
| Polygon / FMP | Rejected | HK coverage weak — fails the FR-002 criterion (≥ 99% field completeness on required fields). |
| Finnhub (news) | Dropped | GDELT covers global English news; the crawler provides the extensible path; one less API surface to govern. |

## 3. Consequences

- **EODHD**: monthly cost accepted (owner decision R7); REST-only keeps adapters trivially mockable in offline tests; single-vendor concentration is mitigated by the adapter layer — vendor swap cost is one adapter, not an architecture change.
- **News**: GDELT gives breadth at zero cost; the crawler carries the injection-risk and parsing-fragility budget, contained by the domain whitelist (blueprint §9.4, tier A).

## 4. Reopen Conditions

- EODHD HK fundamentals field completeness falls below the FR-002 threshold (99% on required fields) → vendor reopen.
- The owner acquires a brokerage account (Futu/Tiger) → broker-API reopen (economics change).
- Crawler reliability on target domains degrades, or a source's terms forbid storage → news-path reopen.

## 5. Registry Note

FR-015 remains **Should**: GDELT alone satisfies FR-003 (Must). The crawler is the extension path, with an explicitly documented future role of Chinese-media support (FR-024). Recorded in the FR-015 `notes` field.

## Amendment 1 (2026-09-30, TP-019) — sync honesty: empty answers fail, benchmark indices refresh daily, detection stops at the cursor

Fifth-audit corrections to the EODHD sync semantics (data/ingest/sync.py):

1. An empty vendor answer proves nothing, for every market action. A
   backfill or incremental that returns 0 bars now fails explicitly and
   leaves the cursor where it was (retried next sync). TP-018b had
   advanced the cursor to the requested end date and reported
   "ok · 0 bars stored; data through <today>" - stale-as-fresh
   (INV-003) - and a symbol whose first backfill came back empty never
   re-planned its history. Because an incremental starts AT the cursor
   (a stored bar), a healthy answer is never empty. Gap-repair keeps
   its TP-018b terminal state (three empty attempts close the gap with
   resolution='no-data').
2. Benchmark indices are ingested daily (REQ-SI-FR-001): an index with
   bars gets an incremental at plan priority 1. They used to be
   backfilled once and never refreshed, which froze the exchange
   calendar derived from them - every completeness pass after the first
   sync was blind to later holes. Cost: one call per index per day.
3. Gap detection for a symbol ends at its cursor: days after the
   cursor are the next incremental's job. With a live calendar, a
   deferred or failed incremental would otherwise enqueue its own
   not-yet-fetched days as gaps and pay for them twice.
4. Closed no-data gaps stay visible: `sync_status` lists them
   (`no_data_gaps`) and `/sync status` prints them, instead of the
   range vanishing from every output the moment it closed.

Residuals recorded as debt (DE-08): empty-attempt counting and the
gap-repair budget share are per run, not per day.

Implements: REQ-SI-FR-001, REQ-SI-INV-003.
