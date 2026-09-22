"""Deterministic news filter: structural gates, relevance scoring, dedup keys.

Stages S1/S2/S3 of the accepted five-stage pipeline
(docs/architecture/news-filtering-design.md v1.0.0; owner decisions D1-D4,
2026-09-17). Pure functions only: no network, no store access, no LLM —
the LLM participates in no filtering decision by design. Transport and
storage (S0/S4/S5) live in news.py (TP-011b).

Live-probe facts baked into the normalization (2026-09-21, TP-011 plan):
titles arrive with spaced punctuation ("closes 1 . 18 pct higher") and
``language`` emits the full word "English".

Implements: REQ-SI-FR-003, REQ-SI-FR-007 (ADR-002)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse

# ---- config-of-record (D2; changes are fixture-calibrated, logged events) ----

#: Tier-A financial domains (design §7 D2, owner-confirmed).
TIER_A_DOMAINS: frozenset[str] = frozenset(
    {
        "reuters.com",
        "bloomberg.com",
        "ft.com",
        "wsj.com",
        "cnbc.com",
        "marketwatch.com",
        "scmp.com",
        "hkexnews.hk",
    }
)

#: General news domains (reputable, not finance-specialized).
GENERAL_NEWS_DOMAINS: frozenset[str] = frozenset(
    {
        "apnews.com",
        "bbc.com",
        "cnn.com",
        "nytimes.com",
        "theguardian.com",
        "washingtonpost.com",
    }
)

#: Content aggregators / republishers (negative signal, not a hard gate).
AGGREGATOR_DOMAINS: frozenset[str] = frozenset(
    {
        "bignewsnetwork.com",
        "marketscreener.com",
        "simplywall.st",
        "streetinsider.com",
        "tipranks.com",
    }
)

#: Blog-platform host fragments (parked/personal page patterns).
AGGREGATOR_DOMAIN_PATTERN = re.compile(r"(blogspot\.|wordpress\.|weebly\.)")

#: Domains quarantined outright at S1 (spam farms; seed set).
BLOCKED_DOMAINS: frozenset[str] = frozenset({"beforeitsnews.com", "stocktwits.com"})

#: Promotional headline phrases (normalized matching; each costs -1).
PROMO_PHRASES: tuple[str, ...] = (
    "stock picks",
    "top stock picks",
    "best stocks to buy",
    "penny stock",
    "pump and dump",
    "guaranteed return",
    "get in early",
    "insider tip",
)

#: Relevance threshold (design §7 D2, owner-confirmed).
TAU: float = 1.0

_SEENDATE_FORMAT = "%Y%m%dT%H%M%SZ"

#: Ticker tokens shorter than this are never standalone evidence
#: (single-letter tickers like "A" collide with ordinary words).
_MIN_TICKER_TOKEN_LEN = 2


# ---- S1: structural gates ----------------------------------------------------


@dataclass(frozen=True)
class GateFailure:
    """A failing S1 gate with the evidence for the quarantine record.

    Implements: REQ-SI-FR-003, REQ-SI-INV-003 (ADR-002)
    """

    gate: str
    detail: str


@dataclass(frozen=True)
class GateResult:
    """S1 verdict: ok, or the single first failing gate.

    Implements: REQ-SI-FR-003 (ADR-002)
    """

    ok: bool
    failure: GateFailure | None = None


def parse_seendate(raw: object) -> datetime | None:
    """Parse a GDELT seendate (yyyyMMddTHHmmssZ) to an aware UTC datetime.

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw, _SEENDATE_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def structural_gates(
    item: Mapping[str, object],
    *,
    window_start: datetime,
    window_end: datetime,
    blocklist: frozenset[str] = BLOCKED_DOMAINS,
) -> GateResult:
    """Run the S1 structural gates; any failure is explicit, never silent.

    Implements: REQ-SI-FR-003, REQ-SI-INV-003 (ADR-002)
    """
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        return GateResult(False, GateFailure("missing_field", "title absent or empty"))
    language = item.get("language")
    if not isinstance(language, str) or language.strip().lower() != "english":
        return GateResult(False, GateFailure("language", f"language={language!r}"))
    seen = parse_seendate(item.get("seendate"))
    if seen is None:
        return GateResult(False, GateFailure("seendate", f"unparseable={item.get('seendate')!r}"))
    if not (window_start <= seen <= window_end):
        return GateResult(
            False,
            GateFailure(
                "window",
                f"seendate={seen.strftime(_SEENDATE_FORMAT)} outside "
                f"[{window_start.strftime(_SEENDATE_FORMAT)}, "
                f"{window_end.strftime(_SEENDATE_FORMAT)}]",
            ),
        )
    url = item.get("url")
    if not isinstance(url, str):
        return GateResult(False, GateFailure("bad_url", f"url={url!r}"))
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return GateResult(False, GateFailure("bad_url", f"scheme/host invalid in {url!r}"))
    domain = item.get("domain")
    if isinstance(domain, str) and domain.lower() in blocklist:
        return GateResult(False, GateFailure("blocklist", f"domain={domain}"))
    return GateResult(True)


# ---- S2: relevance scoring ---------------------------------------------------


@dataclass(frozen=True)
class SymbolEntry:
    """Watchlist-side evidence source for one canonical symbol.

    Implements: REQ-SI-FR-003 (ADR-002)
    """

    canonical_symbol: str
    official_name: str
    aliases: tuple[str, ...] = ()
    ticker_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class MacroGroup:
    """A macro keyword group (design §7 D4); phrase membership is evidence.

    Implements: REQ-SI-FR-003 (ADR-002)
    """

    name: str
    phrases: tuple[str, ...]


@dataclass(frozen=True)
class ScoreResult:
    """S2 outcome for one (item, bucket) pair.

    Implements: REQ-SI-FR-003 (ADR-002)
    """

    bucket: str
    token_evidence: float
    token_sources: tuple[str, ...] = ()
    source_tier: float = 0.0
    negative: float = 0.0
    score: float = 0.0
    keep: bool = False


def normalize_title(title: str) -> str:
    """Normalize a headline for phrase/alias evidence.

    Lowercase; keep letters, digits, ampersand (S&P) and whitespace;
    collapse runs — absorbs GDELT's spaced punctuation ("1 . 18" -> "1 18").

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    lowered = title.lower()
    squeezed = re.sub(r"[^0-9a-z&\s]+", " ", lowered)
    return re.sub(r"\s+", " ", squeezed).strip()


def _phrase_in(norm_title: str, phrase: str) -> bool:
    """Word-boundary containment of a normalized phrase in a title."""
    return re.search(rf"(?:^|\s){re.escape(phrase)}(?:\s|$)", norm_title) is not None


def _ticker_hit(title: str, tokens: Sequence[str]) -> str | None:
    """Case-sensitive word-boundary ticker match; None if no hit."""
    for token in tokens:
        if len(token) < _MIN_TICKER_TOKEN_LEN:
            continue
        if re.search(rf"\b{re.escape(token)}\b", title):
            return token
    return None


def source_tier(domain: object) -> float:
    """Domain tier per the config-of-record (D2).

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    if isinstance(domain, str):
        lowered = domain.lower()
        if lowered in TIER_A_DOMAINS:
            return 1.0
        if lowered in GENERAL_NEWS_DOMAINS:
            return 0.3
    return 0.0


def negative_signals(norm_title: str, domain: object) -> float:
    """Promotional phrase and aggregator/parked-domain penalties.

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    penalty = 0.0
    if any(_phrase_in(norm_title, phrase) for phrase in PROMO_PHRASES):
        penalty -= 1.0
    if isinstance(domain, str):
        lowered = domain.lower()
        if lowered in AGGREGATOR_DOMAINS or AGGREGATOR_DOMAIN_PATTERN.search(lowered):
            penalty -= 1.0
    return penalty


def _result(
    bucket: str,
    token_evidence: float,
    token_sources: tuple[str, ...],
    title: str,
    domain: object,
) -> ScoreResult:
    tier = source_tier(domain)
    negative = negative_signals(normalize_title(title), domain)
    score = token_evidence + tier + negative
    keep = token_evidence >= 1.0 and score >= TAU
    return ScoreResult(
        bucket=bucket,
        token_evidence=token_evidence,
        token_sources=token_sources,
        source_tier=tier,
        negative=negative,
        score=score,
        keep=keep,
    )


def score_against_symbol(title: str, domain: object, entry: SymbolEntry) -> ScoreResult:
    """Score one headline against one symbol bucket.

    token_evidence: +1 ticker token (case-sensitive, word-boundary),
    +1 official-name phrase, +0.5 for any alias containment (capped once).
    Aliases containing the official name do not double-count.

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    norm = normalize_title(title)
    evidence = 0.0
    sources: list[str] = []
    ticker = _ticker_hit(title, entry.ticker_tokens)
    if ticker is not None:
        evidence += 1.0
        sources.append(f"ticker:{ticker}")
    if _phrase_in(norm, normalize_title(entry.official_name)):
        evidence += 1.0
        sources.append(f"official:{entry.official_name}")
    for alias in entry.aliases:
        if _phrase_in(norm, normalize_title(alias)):
            evidence += 0.5
            sources.append(f"alias:{alias}")
            break
    return _result(entry.canonical_symbol, evidence, tuple(sources), title, domain)


def score_against_macro(title: str, domain: object, group: MacroGroup) -> ScoreResult:
    """Score one headline against one macro keyword group (D4).

    Any member phrase in the normalized title is +1.0 token evidence.

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    norm = normalize_title(title)
    evidence = 0.0
    sources: list[str] = []
    for phrase in group.phrases:
        if _phrase_in(norm, phrase):
            evidence += 1.0
            sources.append(f"macro:{phrase}")
            break
    return _result(f"macro:{group.name}", evidence, tuple(sources), title, domain)


@dataclass(frozen=True)
class ItemVerdict:
    """S1 + S2 composition for one raw item.

    Implements: REQ-SI-FR-003, REQ-SI-INV-003 (ADR-002)
    """

    quarantined: GateFailure | None
    bucket_scores: tuple[ScoreResult, ...] = field(default_factory=tuple)

    @property
    def kept_buckets(self) -> tuple[str, ...]:
        """Buckets whose keep rule fired (empty when quarantined).

        Implements: REQ-SI-FR-003, REQ-SI-INV-003 (ADR-002)
        """
        if self.quarantined is not None:
            return ()
        return tuple(score.bucket for score in self.bucket_scores if score.keep)


def evaluate_item(
    item: Mapping[str, object],
    *,
    symbols: Sequence[SymbolEntry],
    macro_groups: Sequence[MacroGroup],
    window_start: datetime,
    window_end: datetime,
    blocklist: frozenset[str] = BLOCKED_DOMAINS,
) -> ItemVerdict:
    """Run S1 then S2 for every bucket; quarantine precedes scoring.

    Implements: REQ-SI-FR-003, REQ-SI-FR-007 (ADR-002)
    """
    gate = structural_gates(item, window_start=window_start, window_end=window_end, blocklist=blocklist)
    if not gate.ok:
        assert gate.failure is not None
        return ItemVerdict(quarantined=gate.failure)
    title = item["title"]
    assert isinstance(title, str)
    domain = item.get("domain")
    scores = [score_against_symbol(title, domain, entry) for entry in symbols]
    scores += [score_against_macro(title, domain, group) for group in macro_groups]
    return ItemVerdict(quarantined=None, bucket_scores=tuple(scores))


# ---- S3: deduplication -------------------------------------------------------


def normalize_url(url: str) -> str:
    """Key A: scheme-insensitive canonical URL.

    Strips ``utm_*`` query parameters, canonicalizes mobile/desktop hosts
    (``m.``/``www.`` prefixes), drops scheme, trailing slash; sorts the
    surviving query parameters.

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    host = re.sub(r"^(?:www|m|mobile)\.", "", host)
    path = parsed.path.rstrip("/") or "/"
    kept = sorted((key, value) for key, value in parse_qsl(parsed.query) if not key.lower().startswith("utm_"))
    query = f"?{urlencode(kept)}" if kept else ""
    return host + path + query


def title_token_set(title: str) -> frozenset[str]:
    """Key B basis: the normalized title's token set.

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    return frozenset(normalize_title(title).split())


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Token-set similarity; 1.0 when both empty (identical empties).

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def survivor_rank(item: Mapping[str, object]) -> tuple[float, str]:
    """The total-order key: higher tier wins, then earlier seendate.

    GDELT seendates sort lexicographically as chronologically
    (yyyyMMddTHHMMSSZ). Non-numeric tiers and non-string seendates are
    rejected explicitly (fail-closed).

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    tier = item["source_tier"]
    seen = item["seendate"]
    if not isinstance(tier, (int, float)) or isinstance(tier, bool):
        raise ValueError("survivor_rank: source_tier must be numeric")
    if not isinstance(seen, str):
        raise ValueError("survivor_rank: seendate must be a string")
    return (-float(tier), seen)


def pick_survivor(items: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
    """Deterministic survivor: highest tier, then earliest seendate.

    GDELT seendates sort lexicographically as chronologically
    (yyyyMMddTHHMMSSZ). Ties beyond both keys are impossible for
    distinct items and rejected with an explicit error.

    Implements: REQ-SI-FR-003 (ADR-002)
    """
    if not items:
        raise ValueError("pick_survivor: empty candidate set")
    ordered = sorted(items, key=survivor_rank)
    if len(ordered) > 1 and survivor_rank(ordered[0]) == survivor_rank(ordered[1]):
        raise ValueError("pick_survivor: ambiguous survivor (tier and seendate tie)")
    return ordered[0]
