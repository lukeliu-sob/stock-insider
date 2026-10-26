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

## Amendment 2 (2026-10-26, TP-035) — news D1 v2: RSS listing track + body backfill track (proposed)

Proposed activation of news-filtering-design.md D1 v2, with the
approach of a reference news-corpus implementation (curated-feed
collection, body extraction, source health, backfill state machine)
ported under this project's governance. Full design:
`news-rss-body-design.md` (decisions D5–D10). Status: **proposed** —
the owner decision is recorded only when TP-035 is approved; no code
lands before that. This amendment, ADR-004 Amendment 7, the design
note, and the D1 activation proposal are the documentation change
set. D1 v2's own precondition (QA-002 passes on the title corpus) is
not yet met; per owner decision D10 it is met by implementing QA-002
first (TP-036), not waived.

1. **RSS listing track**: curated English feeds on tier-A /
   general-news domains join GDELT and EODHD as a third listing
   source, through the unchanged S1–S5 pipeline; per-feed health in
   `news_feed_health`. FR-003's filter-at-ingestion rule is not
   relaxed for named sources.
2. **Body backfill track**: stored rows on the body whitelist gain a
   fetched body via the shared Transport seam; per-domain template
   extraction (the FR-015 mechanism, ingestion side); row state
   machine pending → extracted | failed → unavailable (cap 3 counted
   attempts; transport / throttle failures are reported, never
   counted); per-domain pause after 5 consecutive failures. Bodies
   stored raw with `crawled` provenance; SEC-002 stays at the egress
   boundary. Embeddings unchanged (D8).
3. **Rejected from the reference**: FTS5 (FR-007 vector-only
   tradeoff), Google-News URL decoding (non-vendor scraping), the
   resident scheduler (deployment shape), the real-browser fallback
   (instability), and the dependency set feedparser / trafilatura /
   BeautifulSoup / httpx / tenacity / asyncio (stdlib satisfies the
   fit criteria; one-shot no-retry stands).
4. **Egress**: the whitelist additions are a `shared/` change and are
   governed by ADR-004 Amendment 7 (owner approval), not by this
   amendment; the code hunk ships with the implementation change set.
5. **Storage**: append-only migration v8 (news body columns +
   `news_feed_health`); schema version 8 under the existing
   memory-design §4 rules.

Reopen conditions: template drift below the fixture threshold →
recalibrate; persistent extraction-quality failure → the trafilatura
dependency reopen; a whitelisted domain's terms forbid storage →
remove the domain (robots.txt / terms are also checked by the TP-035
live probe before a domain joins the body whitelist).

Implements: REQ-SI-FR-003, REQ-SI-FR-015, REQ-SI-INV-003.
