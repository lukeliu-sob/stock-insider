# News RSS & Body Design — D1 v2 Activation (Listing + Body Tracks)

| Field | Value |
|---|---|
| Document | `docs/architecture/news-rss-body-design.md` (pre-TP-035 design note) |
| Version | 0.3.0 (owner decisions D5–D10 of 2026-10-26: HK English sources, topical bucket, feedparser + BeautifulSoup, daily cadence, QA-002 first with a Qwen embedding model) |
| Date | 2026-10-26 |
| Registry baseline | `docs/req/requirements.yaml` v0.6.2 (REQ-SI-FR-027 appended, §12) |
| Governs | planned `data/ingest/newsrss.py`, `data/ingest/newsbody.py`; FR-003 (Must), FR-007 input side, FR-015 mechanism (Should), the proposed topical-feed row (§12), INV-003, SEC-003 |
| Related | `news-filtering-design.md` (D1 v2, decisions D1–D4); ADR-002 + Amendment 2; ADR-004 Amendment 7 (egress); ADR-003; `memory-design.md` §2/§4; TP-036 (QA-002) |
| Status | **Proposed** — owner decisions D5–D10 and D10a recorded (§10); implementation gated on TP-035 approval |

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

Decision D10a (owner, 2026-10-26): QA-002 was measured and missed
(E-011 relevance@5 0.768; E-012 held-out 0.720, no query-side variant
reaches 0.8), and the owner accepts the residual for D1 v2. Reasons:
FR-007 (Must) passes its fit criterion (hit@5 0.920, held-out 1.000);
QA-002 is a Should; and the most promising improvement, body-inclusive
embedding, needs the bodies TP-035 collects, so blocking TP-035 on
QA-002 would be circular. QA-002 stays unmet, its assertion stays a
strict expected failure (DE-17), and it is re-measured when
body-inclusive embedding is decided (D8 follow-up).

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
4. The HK English sources added by D5/D6 (The Standard, RTHK, HKFP,
   China Daily HK, news.gov.hk) carry **no evidence yet**: every feed
   URL and every page's fetchability is established by the TP-035 live
   probe. A source that fails the probe is left out, not guessed.

Consequences: the initial feed set is reputable and probe-gated; the
body whitelist starts with server-side-fetchable domains only;
bot-walled tier-A domains stay title-only, reported per run (INV-003).
Chinese-language HK media are out of scope (registry meta
`scope_out_of_scope`, REQ-SI-FR-024) and are not part of this design.

## 3. Scope

Two new tracks inside the daily sync's news section, both isolated
per track exactly like the gdelt/eodhd boundaries (one track failing
never fails another). GDELT and EODHD tracks are untouched (baseline
discipline: extend, never replace). FR-003 is source-agnostic and
GDELT remains a satisfier; FR-015 stays Should with its future
agent-tool scope unaffected — this note reuses its whitelist +
template mechanism on the ingestion side, as D1 v2 already
anticipated ("via the FR-015 whitelist crawler path").

One registry change is required: the topical bucket (§4.1) stores
curated-feed items without symbol or macro token evidence, which
FR-003's "no full firehose" filter-at-ingestion rule does not cover.
It has its own requirement row, REQ-SI-FR-027 (§12, registry
v0.6.2); no existing row changes.

## 4. Track 1 — RSS Listing (`data/ingest/newsrss.py`, planned)

A third S0 listing source feeding the **unchanged** S1–S5 machinery.

- **Config-of-record** `RSS_FEEDS: tuple[FeedSpec, ...]`,
  `FeedSpec(feed_id, url, domain, topical)`; domain is the apex
  **relevance** domain and must appear in the S2 tier lists (D2). It
  is not the fetch host: the feed URL's host is what the egress
  whitelist checks (§8), and the two may differ (BBC: feed host
  `feeds.bbci.co.uk`, relevance domain `bbc.com`). `topical` marks a
  feed whose unmatched items enter the topical bucket (§4.1). Changes
  are logged events. Initial set (D6); every *(live-probe)* URL is
  fixed by the TP-035 probe, and a feed that fails it is dropped from
  the set:

  | feed_id | url | domain | topical |
  |---|---|---|---|
  | `scmp:top` | `https://www.scmp.com/rss/91/feed` | `scmp.com` | yes |
  | `scmp:china` | `https://www.scmp.com/rss/4/feed` | `scmp.com` | yes |
  | `bbc:business` | `https://feeds.bbci.co.uk/news/business/rss.xml` *(live-probe)* | `bbc.com` | yes |
  | `guardian:business` | `https://www.theguardian.com/uk/business/rss` *(live-probe)* | `theguardian.com` | yes |
  | `standard:hk` | *(live-probe)* | `thestandard.com.hk` | yes |
  | `rthk:local` | `https://rthk.hk/rthk/news/rss/e_expressnews_elocal.xml` *(live-probe)* | `rthk.hk` | yes |
  | `hkfp:all` | `https://hongkongfp.com/feed/` *(live-probe)* | `hongkongfp.com` | yes |
  | `chinadailyhk:hk` | *(live-probe)* | `chinadailyhk.com` | yes |
  | `govhk:news` | *(live-probe)* | `news.gov.hk` | yes |

- **Tier lists**: the five HK relevance domains join
  `GENERAL_NEWS_DOMAINS` (+0.3). Under D2 a tier-list change is a
  fixture-calibrated, logged change: the FR-003 precision gate
  (>= 0.8 on `news_corpus_v1.json`) is re-run in the TP-035 change set
  and its result logged.
- **Parsing**: `feedparser` (D7) over the **response bytes** fetched by
  the Transport seam — feedparser is never handed a URL, so it never
  opens a connection of its own (SEC-003). Unparseable input (bozo
  with zero usable entries) is a classified `malformed` failure
  (fail-closed). Item fields: title, link, published, summary —
  entities unescaped, embedded tags stripped deterministically
  (BeautifulSoup `get_text`).
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
  instead: `RSS_LOOKBACK_DAYS = 14` (config-of-record; equal to the
  Key B window). Older items are quarantined with the window gate
  recorded, never stored silently and never dropped silently.
- **Filtering**: each item runs `evaluate_item` against every active
  watchlist symbol and every macro group. For symbol and macro
  buckets the firehose prohibition (FR-003) is not relaxed for named
  sources: an item is stored in those buckets only where token
  evidence fired. Quarantine visibility and the keep rule (tau = 1.0,
  D2) are unchanged.
- **Deduplication**: S3 unchanged — Key A (normalized URL, per
  bucket) and Key B (title token-set Jaccard >= 0.8 within 14 days),
  deterministic survivor rule. Because all sources share the `news`
  table, cross-source dedup falls out for free.
- **Feed health**: `news_feed_health(feed_id, consecutive_failures,
  last_ok_at, last_error)` (migration v8). One feed fetch per day is
  cheap, so failures are recorded and reported, not skipped — the
  run report carries per-feed status (`ok` / classified kind) and the
  counts (kept_new / topical_new / dups / quarantined / rejected).
- **Politeness / transport**: the shared Transport seam (egress
  gate, one shot, no retry — ADR-002); inter-feed pacing reuses
  `INTER_QUERY_SLEEP`. Failure taxonomy: `http | throttle | transport
  | malformed`.
- **Cursor**: informational only, under its own `sync_state` track
  key `news:rss` (never the gdelt key); dedup is the idempotence.

### 4.1 Topical bucket (current-affairs context; D6)

Owner decision: items with limited financial relevance are kept as a
current-affairs source rather than rejected.

- **Admission**: an item from a `topical` feed that matched **no**
  symbol or macro bucket is stored once in the reserved bucket
  `topical` (namespaced like `macro:*`; it cannot collide with a
  symbol). An item that matched a symbol or macro bucket is stored
  there only, never duplicated into `topical`.
- **Gates still apply**: S1 structural gates (language, date, window,
  URL, blocklist) and the S2 negative signals (promotional phrases,
  aggregator patterns) — any negative signal rejects a topical item.
  Only the token-evidence floor is waived, and only for `topical`
  feeds; GDELT and EODHD items never enter `topical`.
- **Volume cap**: at most `TOPICAL_PER_FEED_RUN = 30` new topical rows
  per feed per run (newest first); the overflow is counted in the run
  report, never dropped silently.
- **Dedup and retention**: Key A / Key B within the `topical` bucket;
  the 2-year retention applies unchanged.
- **Not embedded, not retrievable by the agent in v1**: topical rows
  are excluded from the embedding backlog (`pending_news`), so they
  never enter the vector space and cannot crowd `news.search` results
  for symbol queries (this also keeps the QA-002 measurement clean).
  Agent-facing access to `topical` (embedding it plus a registry tool
  or a `news.recent` bucket) is a separate follow-up: it touches
  `agent/registry` (safety-critical) and needs its own plan and an
  ADR-005 amendment.

## 5. Track 2 — Body Backfill (`data/ingest/newsbody.py`, planned)

The D1 v2 body fetch, for stored rows of any source whose domain is
on the body whitelist.

- **Config-of-record** `BODY_WHITELIST` (initial candidates, D5):
  `{cnbc.com, marketwatch.com, thestandard.com.hk, rthk.hk,
  hongkongfp.com, chinadailyhk.com, news.gov.hk}`. A candidate joins
  only after the TP-035 live probe confirms server-side fetchability
  and that robots.txt / terms permit fetching and local storage.
  Every other tier-A domain (reuters, bloomberg, ft, wsj, scmp,
  hkexnews) stays title-only until a probe proves fetchability, and
  is reported as such. `EXTRACTION_TEMPLATES: domain -> CSS selector
  list` — the FR-015 per-domain template mechanism; calibrated on
  version-controlled fixture pages; template drift recalibrates the
  template (a logged config change), never degrades silently.
- **Extraction**: BeautifulSoup (D7, stdlib `html.parser` backend —
  no lxml) over the fetched bytes, selecting the template's CSS
  selectors; script/style/nav/footer/aside/header removed; whitespace
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
  visible, not hidden). Topical rows are eligible like any other row.
- **Storage**: `news.body` holds the extracted text **verbatim, as
  raw evidence**, with `crawled` provenance (`SourceKind.CRAWLED` in
  `shared/tools.py`) whenever it reaches a tool result; SEC-002
  sanitization stays at the egress boundary into model context, never
  at rest (unchanged boundary).
- **Retention**: S5 already lists the body; the 2-year retention
  deletes `body` and the `body_*` columns together with the row.
- **Embeddings and tool output**: unchanged in this change set (D8) —
  embeddings stay title-only, and `news.search` / `news.recent` keep
  their output shapes, so bodies are stored but not yet read by the
  agent. Body-inclusive embedding and body excerpts in tool output
  are option-ledger entries; either one requires the SEC-002
  sanitizer first (news-filtering-design §6 sanitizes before
  embeddings as well as before model context).

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
distinct provenance surfaces (api evidence vs crawled evidence). The
topical bucket needs no schema change: it is a bucket value in the
existing `symbol` column.

## 7. Sync Integration & Status

Both tracks hook into `SyncService.run` after `news/eodhd`, each
inside its own try/except isolation boundary, results under
`report.news["rss"]` / `report.news["body"]`. They run once per daily
sync (D9). Read-only status helpers (`rss_news_status`,
`body_status`) are part of the module contracts; surfacing them in
`sync status` is an optional follow-up (the run report satisfies the
INV-003 visibility floor for v1).

## 8. Egress Whitelist Additions (shared/, owner-gated)

`EGRESS_WHITELIST` gains the feed and body hosts listed in ADR-004
Amendment 7: `scmp.com`, `bbci.co.uk`, `theguardian.com`, `cnbc.com`,
`marketwatch.com`, `thestandard.com.hk`, `rthk.hk`, `hongkongfp.com`,
`chinadailyhk.com`, `news.gov.hk`. These are fetch hosts, not
relevance domains: `bbci.co.uk` is on no S2 tier list and does not
need to be, since BBC items score as `bbc.com` (§4). An entry whose
source fails the live probe is removed from the hunk before it lands.
A `shared/` change requires its linked ADR — ADR-004 Amendment 7, the
ADR that governs `shared/egress.py` — and explicit human approval;
the code hunk lands with the implementation change set, not before.

The embedding endpoint (TP-036) is a provider host, not a news host:
it is allowed through the owner's `EGRESS_EXTRA_HOSTS` entry in
`.env` (ADR-004 Amendment 2), not through this list.

## 9. Deliberately Not Ported from the Reference Implementation

| Rejected | Reason | Reopen trigger |
|---|---|---|
| FTS5 hybrid retrieval | Contradicts the FR-007 vector-only tradeoff (registry v0.6.1); revisit trigger already in the option ledger | Option-ledger revisit |
| Google-News batchexecute URL decoding | Third-party scraping of a non-vendor host; violates the egress whitelist philosophy | — |
| Resident scheduler (APScheduler) | Contradicts blueprint deployment shape; tracks run in the daily sync (D9) | Owner cadence change |
| Real-browser body fallback (Playwright) | Unstable (rate limits, challenges), heavy install, a second egress path to govern; blocked domains stay title-only and are reported | A whitelisted domain proves fetchable only with a browser |
| trafilatura (and its lxml dependency) | Not selected by the owner (D7); BeautifulSoup templates cover the probe-gated whitelist | Persistent fixture-threshold extraction failure |
| httpx / tenacity / asyncio | Transport concerns, not parsing: the shared Transport seam stays the only network path, and its one-shot no-retry rule stands (ADR-002) | — |
| WAL / FTS tuning | Single-writer CLI shape already; store governed by ADR-003 | — |

## 10. Owner Decisions (2026-10-26)

| ID | Decision |
|---|---|
| D5 | Activate D1 v2. `BODY_WHITELIST` candidates: cnbc.com, marketwatch.com, plus the HK English local sources thestandard.com.hk, rthk.hk, hongkongfp.com, chinadailyhk.com, news.gov.hk; each joins only after the TP-035 live probe (fetchability, robots.txt, terms). Bot-walled tier-A domains stay title-only, reported per run. Run parameters at their proposed defaults (30 rows/run, 10/domain, 1.5 s pacing, 3 counted attempts, 5-failure domain pause, 200-character schema) |
| D6 | Feed set per §4 (SCMP ×2, BBC and Guardian business, five HK English sources; all but SCMP probe-gated). Feeds with limited financial relevance are kept: their unmatched items go to the `topical` bucket (§4.1), which needs the §12 registry row. `RSS_LOOKBACK_DAYS = 14` |
| D7 | Two new dependencies approved: `feedparser` (feed parsing) and `beautifulsoup4` (HTML extraction, stdlib parser backend). Both only ever receive bytes from the Transport seam. trafilatura, Playwright, httpx, tenacity and asyncio stay rejected (§9) |
| D8 | Embeddings stay title-only and `news.search` / `news.recent` output shapes stay unchanged; bodies and topical rows are stored but not yet read by the agent; agent-facing access is a follow-up plan |
| D9 | Both tracks run once per daily sync; no scheduler, no ad-hoc CLI surface in v1 |
| D10 | The D1 v2 precondition (§1) is met by implementing QA-002 (TP-036) before TP-035 implementation; no waiver. Embedding model for TP-036: `qwen3.7-text-embedding-flash` (owner-tested) at `https://maas.qianwenaiapi.com/compatible-mode/v1`, with its own key `EMBEDDING_API_KEY`, filled in by the owner |
| D10a | **Owner-decided 2026-10-26**: QA-002 missed (E-011, E-012); the residual is accepted for D1 v2 (§1). TP-035 may proceed on its own approval; QA-002 stays unmet (DE-17) and is re-measured with the body-inclusive embedding decision |

## 11. Test Mapping (TP-035)

`test/offline/test_ingest_newsrss.py` and
`test/offline/test_ingest_newsbody.py` (fixtures + fake transport; no
network), plus migration and sync-isolation tests in the existing
store and sync suites: positive (bucket admission end to end; RSS 2.0
/ Atom / RDF parsing; both timestamp forms; topical admission of an
unmatched item from a topical feed; extraction + state advance; Key A
survivor; Key B cross-source dedup; v7 -> v8 migration), negative
(irrelevant GDELT/EODHD item stores nothing; matched item never
duplicated into topical; negative-signal item rejected from topical;
topical cap overflow counted; topical rows never enter the embedding
backlog; unparseable date and out-of-lookback item quarantined; short
extraction stores nothing; attempts cap -> unavailable;
transport/throttle failures do not count attempts; HTTP/transport
failures classified and isolated; one track failing leaves the others
complete; feed health accounting; domain pause with `paused` counts
in the report), adversarial (egress-denied feed fails closed with
zero writes; feedparser and BeautifulSoup never open a connection;
non-whitelisted body domain never fetched — 0 successes per FR-015a;
body stored raw — SEC-002 boundary is egress, not rest). Mutation
checks are listed in TP-035.

## 12. Registry Change (owner-approved, registry v0.6.2)

The topical bucket stores items without symbol or macro token
evidence, which FR-003 ("filtered at ingestion, no full firehose")
does not cover. The owner approved appending this row (2026-10-26;
append-only, no existing row changes); its `regression_scope` carries
the `future/` prefix until the suite exists:

```yaml
  - id: REQ-SI-FR-027
    type: functional
    statement: >-
      Items from a curated, config-of-record list of English news feeds
      that match no watchlist symbol or macro group are stored in a
      separate topical bucket as current-affairs context. The bucket
      never receives items from vendor or firehose sources, keeps the
      structural gates, negative signals, deduplication and 2-year
      retention of FR-003, and is excluded from symbol-scoped and
      default semantic retrieval.
    fit_criterion: >-
      (a) An unmatched fixture item from a curated feed lands in the
      topical bucket; the same item from GDELT or EODHD stores nothing.
      (b) A matched item is stored in its symbol or macro bucket only.
      (c) Topical rows never appear in default news.search results.
      (d) Per-feed volume caps are enforced and overflow is reported.
    priority: Should
    tradeoff: >-
      A bounded, curated exception to the FR-003 firehose prohibition,
      accepted for current-affairs context; kept out of retrieval so
      symbol-query relevance (QA-002) is not diluted.
    source: "Owner decision D6, 2026-10-26 (news-rss-body-design.md)"
    status: conceptual
    depends_on: [REQ-SI-FR-003]
    regression_trigger: true
    regression_scope: ["future/test/offline/test_ingest_newsrss.py"]
```

The meta `scope_must_do` entry for English news ingestion now names
the curated topical bucket (REQ-SI-FR-027). The TP-035 implementation
PR drops the `future/` prefix once the suite lands.
