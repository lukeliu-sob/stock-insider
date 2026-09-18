# News Filtering Design — GDELT Ingestion Pipeline

| Field | Value |
|---|---|
| Document | `docs/architecture/news-filtering-design.md` (pre-TP-011 design note) |
| Version | 1.0.0 |
| Date | 2026-09-17 |
| Registry baseline | `docs/req/requirements.yaml` v0.3.2 |
| Governs | `data/ingest` news path; FR-003 (Must), FR-007 input side, QA-002 fixture discipline, SEC-002 layer one |
| Related | ADR-002 (vendor), ADR-003 (storage), memory-design.md §2 |
| Status | **Accepted** (owner confirmed decisions D1-D4, this date) |

## 1. Purpose

Fixes the detailed design of the news relevance filter before TP-011
implementation, per owner request ("GDELT filtering needs further
discussion"). The filter is fully deterministic: no LLM participates in
any filtering decision (the LLM appears only at FR-009 event scoring,
gated separately).

## 2. Verified External Facts (2026-09-17)

1. **GDELT DOC 2.0 API** (`api.gdeltproject.org/api/v2/doc/doc`): free,
   no key, JSON output; boolean queries with quoted phrases, `NEAR`,
   `sourcelang:`, `domain:` operators; `mode=artlist` returns **article
   metadata only** (title, url, domain, seendate, language,
   sourcecountry) — **no article body**; rolling **3-month** search
   window; throttles aggressive clients.
2. Consequences: filtering operates at the **headline level** in v1;
   the initial corpus cannot exceed 3 months (the 2-year retention
   window accumulates forward only); a polite query pace with a
   resumable cursor is mandatory.

## 3. Content Strategy (Decision D1 — phased, owner-confirmed)

- **v1 (TP-011)**: store and embed title + domain + published date only
  ("title corpus"). FR-003 (Must) is satisfied by GDELT alone, matching
  ADR-002.
- **v2 (after QA-002 passes on the title corpus)**: extend to body
  fetching for tier-A domains via the FR-015 whitelist crawler path.
  Activation requires an explicit owner decision recorded here.

## 4. Filter Pipeline (five stages, fail-closed, fully deterministic)

```
GDELT query (S0) -> structural gates (S1) -> relevance scoring (S2)
    -> deduplication (S3) -> storage + quarantine (S4) -> retention (S5)
```

### S0 — Query construction (per sync, cursor-driven)

Per active watchlist symbol, one query per sync:

```
("Official Name" OR "Alias 1" OR ... OR TickerWithContext) sourcelang:english
  &mode=artlist&format=json&maxrecs=75&timespan=<since cursor>
```

Macro track: fixed keyword groups (§7 D4), same machinery — group
membership is the token evidence. Queries are constructed from the
symbol map (official names + aliases); each stored article records
which query produced it (query provenance).

### S1 — Structural gates (any failure -> quarantine, never silent drop)

- `language == english`; `seendate` parseable; published within the
  cursor window; URL parses with http(s) scheme; domain not on the
  blocklist. Rejected items are written to `news_quarantine` with the
  failing gate recorded (INV-003 visibility).

### S2 — Relevance scoring (the FR-003 filter; pure functions, golden outputs)

```
score = token_evidence + source_tier + negative_signals
```

- `token_evidence` (**mandatory: at least one, else reject**):
  +1 exact ticker token, word-boundary, case-sensitive ("AAPL" is not
  "aapl"); +1 official-name exact phrase; +0.5 normalized alias
  containment.
- `source_tier`: +1.0 tier-A financial domain whitelist; +0.3 general
  news domain; 0 unknown domain.
- `negative_signals`: -1 promotional phrase blocklist ("stock picks"
  and similar); -1 aggregator/parked-domain patterns.
- **Keep rule**: `token_evidence >= 1 AND score >= tau`, with
  **tau = 1.0** (Decision D2, owner-confirmed). Any change to tau or
  the tier lists is a fixture-calibrated, logged change.

### S3 — Deduplication (two keys, deterministic survivor rule)

- **Key A**: normalized URL (strip `utm_*` parameters, mobile/desktop
  canonicalization, trailing slash, scheme).
- **Key B**: normalized-title token set; Jaccard >= 0.8 against stored
  articles in the same symbol bucket within 14 days -> duplicate.
- **Survivor rule**: keep the highest `(source_tier, earliest
  seendate)` — total order, no ambiguity.

### S4 — Storage + provenance

Stored rows carry: `source_kind=api`, `produced_at`, fetch timestamp,
**query provenance**, relevance score, keep decision. Rejected items
land in `news_quarantine` (audit trail).

### S5 — Retention

Articles older than 2 years: body/embedding/metadata deleted (v1:
title+embedding+metadata). Event-score snapshots (headline + URL +
score) are retained indefinitely (memory-design §2).

## 5. Relevance Precision Measurement (FR-003 fit criterion)

- Hand-labeled fixture corpus of ~200 headlines (version-controlled
  JSON), including adversarial classes: same-name different company,
  ticker collisions (e.g. the bare token "700"), macro-only mentions,
  promotional spam.
- Gate: **precision of keep decisions >= 0.8** on the fixture corpus.
  Recall is recorded but not gated; tau calibration reports both to the
  evaluation logbook.
- Rule changes require fixture expectation updates in the same change
  set (append-only discipline applied to fixtures).

## 6. Sanitization Interface (SEC-002 layer one; implemented TP-012)

Headlines are untrusted input. Before entering embeddings and model
context: strip control characters; neutralize instruction-like patterns
("ignore previous", "system:"). The helper lives in `shared/` (the
only legal common dependency of `agent/context` and `data/ingest`).
Storage keeps the original title unmodified (raw evidence); only the
egress path into model context sanitizes.

## 7. Confirmed Decisions (owner, 2026-09-17)

| ID | Decision |
|---|---|
| D1 | Phased content strategy: v1 title corpus; v2 body fetch for tier-A domains after QA-002 passes |
| D2 | tau = 1.0; tier lists are config-of-record (initial tier-A: reuters.com, bloomberg.com, ft.com, wsj.com, cnbc.com, marketwatch.com, scmp.com, hkexnews.hk) |
| D3 | Initial corpus limited to 3 months (GDELT hard constraint) — accepted; 2-year window accumulates forward |
| D4 | Initial macro keyword groups: Federal Reserve / Fed rate / FOMC; CPI / PCE inflation; China GDP / China PMI / Caixin; HKMA / base rate / HIBOR; USDCNY / yuan; tariff(s) |

## 8. Sync Cadence and Pacing

Daily, after market-data sync, or independent. One query per symbol;
inter-query sleep (5 s default); resumable per-track cursor in
`sync_state`. GDELT failures (HTTP error, malformed JSON, throttle)
produce explicit failure reports and no partial silent writes (INV-003;
transactional per batch).

## 9. Test Mapping (implemented in TP-011)

`test/offline/test_ingest_news.py`: per-stage unit tests; both dedup
keys; retention under synthetic timestamps; quarantine visibility;
fixture precision gate >= 0.8; fault injection (GDELT down / malformed
JSON / throttle); adversarial classes from §5.
