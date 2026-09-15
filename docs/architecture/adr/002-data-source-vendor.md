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
