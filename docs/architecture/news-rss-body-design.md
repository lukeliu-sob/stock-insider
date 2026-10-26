# News RSS & Body Design — D1 v2 Activation (Listing + Body Tracks)

| Field | Value |
|---|---|
| Document | `docs/architecture/news-rss-body-design.md` (pre-TP-035 design note) |
| Version | 0.2.0 (review pass: D10 precondition, egress under ADR-004 Am7, fetch host vs relevance domain, attempt counting, `not_applicable` state, RSS source/provenance/window) |
| Date | 2026-10-26 |
| Registry baseline | `docs/req/requirements.yaml` v0.6.1 |
| Governs | planned `data/ingest/newsrss.py`, `data/ingest/newsbody.py`; FR-003 (Must), FR-007 input side, FR-015 mechanism (Should), INV-003, SEC-003 |
| Related | `news-filtering-design.md` (D1 v2, decisions D1–D4); ADR-002 + Amendment 2; ADR-004 Amendment 7 (egress); ADR-003; `memory-design.md` §2/§4 |
| Status | **Proposed** — awaiting owner decisions D5–D9 (§10); D10 decided (QA-002 first, TP-036) |

## 1. Purpose

Fixes the design of the `news-filtering-design.md` D1 v2 activation
before any implementation (TP-035). A reference implementation was
evaluated (an external news-corpus project: curated-feed collection,
body extraction, FTS retrieval, source health, backfill state
machine). This note records what is adopted, how it maps onto the
accepted five-stage pipeline, and what is rejected under this
project's governance. Nothing in this note is implemented yet: code
lands only in the TP-035 change set, after plan approval.

Precondition gap: D1 v2 is defined to follow a QA-002 pass on the
title corpus. QA-002 is still `conceptual` and its verification suite
(`test/offline/test_retrieval.py`) does not exist, so the precondition
is not met. Decision D10 (§10, owner, 2026-10-26): QA-002 is
implemented as its own feature under TP-036, not waived. TP-035
implementation starts only after the TP-036 suite has merged and
passes both gates; a TP-036 miss keeps TP-035 blocked pending an
owner decision.

## 2. Verified External Facts (2026-10, reference-implementation evidence)

1. **SCMP RSS endpoints are live** (`/rss/91/feed` top, `/rss/4/feed`
   china). Reuters and WSJ public RSS are dead (frozen / bot-walled);
   their headlines keep arriving via GDELT — no replacement needed.
2. **BBC and The Guardian publish RSS**; the business-section endpoint
   URLs are verified by the TP-035 live probe before the first live
   run (offline tests use fixtures regardless).
3. **Article pages bot-wall plain HTTP clients** on several tier-A
   domains (reference evidence: AP, Politico, SCMP, Sky, News24
   return 403 to non-browser clients). Page fetchability, not feed
   availability, bounds the body whitelist.
4. feedparser / trafilatura / BeautifulSoup would simplify parsing and
   extraction but are new third-party dependencies.

Consequences: the initial feed set is small and reputable; the body
whitelist starts with server-side-fetchable domains only; bot-walled
tier-A domains stay title-only, reported per run (INV-003).

## 3. Scope

Two new tracks inside the daily sync's news section, both isolated
per track exactly like the gdelt/eodhd boundaries (one track failing
never fails another). GDELT and EODHD tracks are untouched (baseline
discipline: extend, never replace). No registry rows change: FR-003
is source-agnostic and GDELT remains a satisfier; FR-015 stays
Should with its future agent-tool scope unaffected — this note reuses
its whitelist + template mechanism on the ingestion side, as D1 v2
already anticipated ("via the FR-015 whitelist crawler path").

## 4. Track 1 — RSS Listing (`data/ingest/newsrss.py`, planned)

A third S0 listing source feeding the **unchanged** S1–S5 machinery.

- **Config-of-record** `RSS_FEEDS: tuple[FeedSpec, ...]`,
  `FeedSpec(feed_id, url, domain)`; domain is the apex **relevance**
  domain and must appear in the S2 tier lists (D2). It is not the
  fetch host: the feed URL's host is what the egress whitelist checks
  (§8), and the two may differ (BBC: feed host `feeds.bbci.co.uk`,
  relevance domain `bbc.com`). Changes are logged events.
  Initial set (D6):

  | feed_id | url | domain |
  |---|---|---|
  | `scmp:top` | `https://www.scmp.com/rss/91/feed` | `scmp.com` |
  | `scmp:china` | `https://www.scmp.com/rss/4/feed` | `scmp.com` |
  | `bbc:business` | `https://feeds.bbci.co.uk/news/business/rss.xml` *(live-probe)* | `bbc.com` |
  | `guardian:business` | `https://www.theguardian.com/uk/business/rss` *(live-probe)* | `theguardian.com` |

- **Parsing**: stdlib `xml.etree` only (RSS 2.0, Atom, RDF);
  namespace-agnostic local-name matching; unparseable XML or zero
  usable items is a classified `malformed` failure (fail-closed).
  Item fields: title, link, published, summary — entities unescaped,
  embedded tags stripped deterministically.
- **Item mapping**: `{title, url, domain (from feed spec), seendate,
  language: "English" (config-of-record), content (feed excerpt — raw
  evidence, same role as EODHD content)}`. Timestamps accepted in RFC
  822 or ISO 8601, normalized to the sortable seendate form; an
  unparseable date maps to None and is **quarantined at S1**, never
  guessed.
- **Domain vs link**: `domain` comes from the feed spec, never from
  the item link, so a BBC item linking to `bbc.co.uk` still scores as
  `bbc.com`. The link itself is stored as `url` and is the Key A input
  after the existing normalization (no cross-host rewriting is added).
- **Source and provenance**: rows and quarantine entries carry
  `source = 'rss'` (the v5 discriminator, so per-source counts work
  unchanged); the S4 query-provenance field holds the `feed_id`;
  `source_kind` stays `api` (structured feed listing).
- **S1 window gate**: the RSS cursor is informational, so the S1
  "published within the cursor window" gate uses a fixed lookback
  instead: `RSS_LOOKBACK_DAYS = 14` (config-of-record, proposed; equal
  to the Key B window). Older items are quarantined with the window
  gate recorded, never stored silently and never dropped silently.
- **Filtering**: each item runs `evaluate_item` against every active
  watchlist symbol and every macro group. The firehose prohibition
  (FR-003) is not relaxed for named sources: an item is stored only
  in buckets where token evidence fired. Quarantine visibility and
  the keep rule (tau = 1.0, D2) are unchanged.
- **Deduplication**: S3 unchanged — Key A (normalized URL, per
  bucket) and Key B (title token-set Jaccard >= 0.8 within 14 days),
  deterministic survivor rule. Because all sources share the `news`
  table, cross-source dedup falls out for free.
- **Feed health**: `news_feed_health(feed_id, consecutive_failures,
  last_ok_at, last_error)` (migration v8). One feed fetch per day is
  cheap, so failures are recorded and reported, not skipped — the
  run report carries per-feed status (`ok` / classified kind) and the
  counts (kept_new / dups / quarantined / rejected).
- **Politeness / transport**: the shared Transport seam (egress
  gate, one shot, no retry — ADR-002); inter-feed pacing reuses
  `INTER_QUERY_SLEEP`. Failure taxonomy: `http | throttle | transport
  | malformed`.
- **Cursor**: informational only, under its own `sync_state` track
  key `news:rss` (never the gdelt key); dedup is the idempotence.

## 5. Track 2 — Body Backfill (`data/ingest/newsbody.py`, planned)

The D1 v2 body fetch, for stored rows of any source whose domain is
on the body whitelist.

- **Config-of-record** `BODY_WHITELIST` (initial, D5):
  `{cnbc.com, marketwatch.com}` — server-side fetchable; every other
  tier-A domain (reuters, bloomberg, ft, wsj, scmp, hkexnews) stays
  title-only until a live probe proves fetchability, and is reported
  as such. `EXTRACTION_TEMPLATES: domain -> ((tag, class-substring),
  ...)` — the FR-015 per-domain template mechanism; calibrated on
  version-controlled fixture pages; template drift recalibrates the
  template (a logged config change), never degrades silently.
- **Extraction**: stdlib `html.parser` collector anchored on the
  template's (tag, class-substring) pairs; void elements never open
  depth; script/style/nav/footer/aside/header skipped; whitespace
  collapsed. **Extraction schema (FR-015b)**: a valid body has >= 200
  characters; anything less stores nothing and the row advances to
  `failed`.
- **State machine** (per row): `not_applicable` (domain not on the
  body whitelist; the title-only rows the run report counts) ->
  `pending` (promoted at run start when its domain is whitelisted) ->
  `extracted | failed`; after 3 counted attempts the row is terminal
  `unavailable` — a recorded absence (the same honesty rule as
  sync_gaps no-data closure, TP-018b), never a silent retry forever
  and never re-selected.
- **Which failures count**: only failures that say something about
  the article count toward the cap — HTTP 4xx and extraction failures
  (below the schema). `transport` and `throttle` failures, and HTTP
  5xx, are reported per run but do not increment `body_attempts`: a
  local outage or a throttled host must not turn reachable articles
  into permanent `unavailable` rows (INV-003: an infrastructure
  failure is not evidence that content is absent).
- **Run shape**: newest-first selection over whitelisted pending
  rows; caps 30 rows/run, 10 rows/domain; 1.5 s inter-fetch pacing; a
  domain failing 5 times consecutively is paused for the rest of the
  run, its remaining rows counted as `paused` in the report (INV-003:
  visible, not hidden).
- **Storage**: `news.body` holds the extracted text **verbatim, as
  raw evidence**, with `crawled` provenance (`SourceKind.CRAWLED` in
  `shared/tools.py`) whenever it reaches a tool result; SEC-002
  sanitization stays at the egress boundary into model context, never
  at rest (unchanged boundary).
- **Retention**: S5 already lists the body; the 2-year retention
  deletes `body` and the `body_*` columns together with the row.
- **Embeddings**: deliberately unchanged in this change set (D8) —
  mixing title-only and title+body vectors in one sqlite-vec space
  needs its own owner decision; recorded as an option-ledger entry.
  That entry carries one condition: if bodies are ever embedded, they
  pass the SEC-002 sanitizer first (news-filtering-design §6 sanitizes
  before embeddings as well as before model context).

## 6. Storage Design (migration v8, append-only)

```sql
ALTER TABLE news ADD COLUMN body TEXT;
ALTER TABLE news ADD COLUMN body_status TEXT NOT NULL DEFAULT 'not_applicable';
ALTER TABLE news ADD COLUMN body_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE news ADD COLUMN body_fetched_at TEXT;
CREATE TABLE news_feed_health (
    feed_id TEXT PRIMARY KEY,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_ok_at TEXT,
    last_error TEXT
);
```

`SCHEMA_VERSION` becomes 8; the existing refuse-newer-schema rule
(memory-design §4) applies unchanged. Existing rows start
`not_applicable`; the body track promotes a row to `pending` only when
its domain is on the body whitelist (the whitelist is config, so the
migration does not encode it). Removing a domain from the whitelist
leaves its `extracted` rows intact and stops selection of the rest.
The vendor `content` column (v5) and the new `body` column remain
distinct provenance surfaces (api evidence vs crawled evidence).

## 7. Sync Integration & Status

Both tracks hook into `SyncService.run` after `news/eodhd`, each
inside its own try/except isolation boundary, results under
`report.news["rss"]` / `report.news["body"]`. Read-only status
helpers (`rss_news_status`, `body_status`) are part of the module
contracts; surfacing them in `sync status` is an optional follow-up
(the run report satisfies the INV-003 visibility floor for v1).

## 8. Egress Whitelist Additions (shared/, owner-gated)

`EGRESS_WHITELIST` gains: `scmp.com`, `bbci.co.uk`,
`theguardian.com` (feed hosts), `cnbc.com`, `marketwatch.com` (body
hosts). These are fetch hosts, not relevance domains: `bbci.co.uk` is
on no S2 tier list and does not need to be, since BBC items score as
`bbc.com` (§4). A `shared/` change requires its linked ADR — ADR-004
Amendment 7, the ADR that governs `shared/egress.py` — and explicit
human approval; the code hunk lands with the implementation change
set, not before.

## 9. Deliberately Not Ported from the Reference Implementation

| Rejected | Reason | Reopen trigger |
|---|---|---|
| FTS5 hybrid retrieval | Contradicts the FR-007 vector-only tradeoff (registry v0.6.1); revisit trigger already in the option ledger | Option-ledger revisit |
| Google-News batchexecute URL decoding | Third-party scraping of a non-vendor host; violates the egress whitelist philosophy | — |
| Resident scheduler (APScheduler) | Contradicts blueprint deployment shape; tracks run in the daily sync | Owner cadence change |
| Real-browser body fallback | Unstable (rate limits, challenges); blocked domains stay title-only and are reported | A whitelisted domain proves fetchable only with a browser |
| feedparser / trafilatura / BeautifulSoup / httpx / tenacity / asyncio | New dependencies; stdlib satisfies the fit criteria; the seam's one-shot no-retry rule stands (ADR-002) | Persistent fixture-threshold extraction failure -> trafilatura reopen |
| WAL / FTS tuning | Single-writer CLI shape already; store governed by ADR-003 | — |

## 10. Decisions Requiring Owner Confirmation

| ID | Decision (proposed) |
|---|---|
| D5 | Activate D1 v2 with initial `BODY_WHITELIST` candidates `{cnbc.com, marketwatch.com}`, each joining only after the TP-035 live probe confirms server-side fetchability and that robots.txt / terms permit fetching and local storage; bot-walled tier-A domains stay title-only, reported per run |
| D6 | Initial feed set per §4 (SCMP ×2 with reference evidence; BBC / Guardian business pending the TP-035 live probe) |
| D7 | Stdlib-only implementation; all reference dependencies rejected (§9) |
| D8 | Embeddings and `news.search` / `news.recent` output shapes unchanged; body-inclusive embedding deferred as an option-ledger entry |
| D9 | Both tracks run in the daily sync cadence; no scheduler, no ad-hoc CLI surface in v1 |
| D10 | **Owner-decided 2026-10-26**: the D1 v2 precondition (§1) is met by implementing QA-002 (TP-036: retrieval relevance suite on the title corpus) before TP-035 implementation; no waiver |

## 11. Test Mapping (TP-035)

`test/offline/test_ingest_newsrss.py` and
`test/offline/test_ingest_newsbody.py` (fixtures + fake transport; no
network), plus migration and sync-isolation tests in the existing
store and sync suites: positive (bucket admission end to end; RSS 2.0
/ Atom / RDF parsing; both timestamp forms; extraction + state
advance; Key A survivor; Key B cross-source dedup; v7 -> v8
migration), negative (irrelevant item stores nothing; unparseable
date and out-of-lookback item quarantined; short extraction stores
nothing; attempts cap -> unavailable; transport/throttle failures do
not count attempts; HTTP/transport failures classified and isolated;
one track failing leaves the others complete; feed health
accounting; domain pause with `paused` counts in the report),
adversarial (egress-denied feed fails closed with zero writes;
non-whitelisted body domain never fetched — 0 successes per FR-015a;
body stored raw — SEC-002 boundary is egress, not rest). Mutation
checks are listed in TP-035.
