"""Offline tests for the deterministic news filter (S1/S2/S3, TP-011a).

Covers structural gates with quarantine visibility, golden scoring
breakdowns, the mandatory token-evidence floor, ticker-collision
adversarials, GDELT spaced-punctuation normalization, dedup keys and
survivor ordering, and the fixture-corpus precision gate (FR-003 fit
criterion; QA-002).

Implements: REQ-SI-FR-003, REQ-SI-FR-007, REQ-SI-QA-002 (ADR-002)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stockinsider.data.ingest.newsfilter import (
    MacroGroup,
    SymbolEntry,
    evaluate_item,
    jaccard,
    normalize_url,
    parse_seendate,
    pick_survivor,
    score_against_macro,
    score_against_symbol,
    structural_gates,
    title_token_set,
)

# Companion configuration for the fixture corpus (QA-002): the symbol
# map and macro groups the corpus was labeled against.
SYMBOLS = (
    SymbolEntry("0700.HK", "Tencent Holdings", ("Tencent",), ("0700",)),
    SymbolEntry("AAPL.US", "Apple Inc", ("Apple",), ("AAPL",)),
    SymbolEntry("AMZN.US", "Amazon.com Inc", ("Amazon",), ("AMZN",)),
    SymbolEntry("MSFT.US", "Microsoft Corporation", ("Microsoft",), ("MSFT",)),
    SymbolEntry("NVDA.US", "NVIDIA Corporation", ("NVIDIA",), ("NVDA",)),
    SymbolEntry("TSLA.US", "Tesla Inc", ("Tesla",), ("TSLA",)),
    SymbolEntry("9988.HK", "Alibaba Group Holding", ("Alibaba", "Alibaba Group"), ("9988",)),
    SymbolEntry("HSI.INDX", "Hang Seng Index", ("Hang Seng",), ("HSI",)),
    SymbolEntry("A.US", "Agilent Technologies", ("Agilent",), ("A",)),
)

MACROS = (
    MacroGroup("fed", ("federal reserve", "fed rate", "fomc", "the fed")),
    MacroGroup("inflation", ("cpi", "pce", "inflation")),
    MacroGroup("china", ("china gdp", "china pmi", "caixin")),
    MacroGroup("hkma", ("hkma", "base rate", "hibor")),
    MacroGroup("yuan", ("usdcny", "yuan")),
    MacroGroup("tariff", ("tariff", "tariffs")),
)

WINDOW_START = datetime(2026, 9, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 9, 22, tzinfo=timezone.utc)

CORPUS_PATH = Path(__file__).resolve().parent / "fixtures" / "news_corpus_v1.json"

_KNOWN_CLASSES = frozenset(
    {
        "aggregator_ticker",
        "alias_insufficient",
        "alias_only_general",
        "alias_only_unknown",
        "hsi_tierA",
        "macro_adversarial",
        "macro_true",
        "missing_title",
        "official_phrase",
        "positive_ticker_general",
        "positive_ticker_tierA",
        "positive_ticker_unknown",
        "promo",
        "quarantine_blocklist",
        "quarantine_date",
        "quarantine_lang",
        "quarantine_url",
        "quarantine_window",
        "same_name_tierA",
        "same_name_unknown",
        "tencent_hkexnews",
        "ticker_alias_combo",
        "ticker_collision",
    }
)


def _evaluate(item: dict) -> tuple[str, ...]:
    verdict = evaluate_item(
        item,
        symbols=SYMBOLS,
        macro_groups=MACROS,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    return verdict.kept_buckets


def _gate(item: dict):
    return structural_gates(item, window_start=WINDOW_START, window_end=WINDOW_END)


# ---- S1: structural gates ----------------------------------------------------


def test_s1_language_backstop_quarantines_non_english() -> None:
    item = {
        "title": "\u82f9\u679c\u516c\u53f8\u53d1\u5e03\u65b0\u6b3e\u624b\u673a",
        "language": "Chinese",
        "seendate": "20260918T090000Z",
        "url": "https://www.example.com/a",
        "domain": "example.com",
    }
    result = _gate(item)
    assert not result.ok
    assert result.failure is not None and result.failure.gate == "language"


def test_s1_unparseable_seendate_quarantines() -> None:
    item = {
        "title": "Apple Inc announces fall event",
        "language": "English",
        "seendate": "2026-09-18T09:00:00Z",
        "url": "https://www.reuters.com/a",
        "domain": "reuters.com",
    }
    result = _gate(item)
    assert not result.ok
    assert result.failure is not None and result.failure.gate == "seendate"


def test_s1_out_of_window_quarantines() -> None:
    item = {
        "title": "Apple Inc WWDC recap",
        "language": "English",
        "seendate": "20260601T120000Z",
        "url": "https://www.reuters.com/a",
        "domain": "reuters.com",
    }
    result = _gate(item)
    assert not result.ok
    assert result.failure is not None and result.failure.gate == "window"


def test_s1_bad_url_quarantines() -> None:
    item = {
        "title": "Microsoft patch notes",
        "language": "English",
        "seendate": "20260918T090000Z",
        "url": "ftp://files.example.com/a.pdf",
        "domain": "example.com",
    }
    result = _gate(item)
    assert not result.ok
    assert result.failure is not None and result.failure.gate == "bad_url"


def test_s1_blocklist_domain_quarantines() -> None:
    item = {
        "title": "AAPL to the moon",
        "language": "English",
        "seendate": "20260918T090000Z",
        "url": "https://beforeitsnews.com/a",
        "domain": "beforeitsnews.com",
    }
    result = _gate(item)
    assert not result.ok
    assert result.failure is not None and result.failure.gate == "blocklist"


def test_s1_missing_title_quarantines() -> None:
    item = {
        "title": "",
        "language": "English",
        "seendate": "20260918T090000Z",
        "url": "https://www.reuters.com/a",
        "domain": "reuters.com",
    }
    result = _gate(item)
    assert not result.ok
    assert result.failure is not None and result.failure.gate == "missing_field"


def test_seendate_parses_to_utc() -> None:
    parsed = parse_seendate("20260921T101500Z")
    assert parsed is not None and parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.hour == 10


# ---- S2: scoring --------------------------------------------------------------


def test_score_golden_breakdowns() -> None:
    aapl = SYMBOLS[1]
    # ticker + alias on tier-A
    r = score_against_symbol("Apple shares rise after AAPL earnings beat", "reuters.com", aapl)
    assert r.token_evidence == 1.5
    assert r.source_tier == 1.0
    assert r.negative == 0.0
    assert r.score == 2.5
    assert r.keep
    assert r.token_sources == ("ticker:AAPL", "alias:Apple")
    # ticker only on unknown domain: boundary keep at exactly tau
    r2 = score_against_symbol("AAPL options volume spikes", "marketrealist.com", aapl)
    assert r2.token_evidence == 1.0 and r2.score == 1.0 and r2.keep
    # alias alone on tier-A: floor rejects despite score 1.5
    r3 = score_against_symbol("Tencent wins approval for titles", "reuters.com", SYMBOLS[0])
    assert r3.token_evidence == 0.5 and r3.score == 1.5 and not r3.keep
    # promo negative
    r4 = score_against_symbol("Top stock picks: buy AAPL now", "pennysheet.example", aapl)
    assert r4.token_evidence == 1.0 and r4.negative == -1.0 and r4.score == 0.0 and not r4.keep
    # official phrase on general tier
    r5 = score_against_symbol("Microsoft Corporation declares dividend", "nytimes.com", SYMBOLS[3])
    assert r5.token_evidence == 1.5 and r5.score == 1.8 and r5.keep
    # aggregator penalty with ticker on aggregator
    r6 = score_against_symbol("MSFT fair value snapshot updated", "simplywall.st", SYMBOLS[3])
    assert r6.score == 0.0 and not r6.keep


def test_score_golden_macro() -> None:
    fed = MACROS[0]
    r = score_against_macro("Federal Reserve holds rates steady", "reuters.com", fed)
    assert r.bucket == "macro:fed"
    assert r.token_evidence == 1.0 and r.score == 2.0 and r.keep
    r2 = score_against_macro("FedEx expands European fleet", "logisticsworld.example", fed)
    assert r2.token_evidence == 0.0 and not r2.keep
    r3 = score_against_macro("FOMO grips retail traders", "marketrealist.com", fed)
    assert r3.token_evidence == 0.0 and not r3.keep


def test_token_evidence_mandatory_despite_tier() -> None:
    verdict = _evaluate(
        {
            "title": "Central banks coordinate on payment rails",
            "language": "English",
            "seendate": "20260918T090000Z",
            "url": "https://www.reuters.com/a",
            "domain": "reuters.com",
        }
    )
    assert verdict == ()


def test_ticker_collision_adversarials() -> None:
    for title in (
        "Hong Kong reports 700 new flu cases in weekly update",  # 700 != 0700
        "aapl registry opens for agricultural producers",  # case-sensitive
        "RHSI hospitality index slips as bookings soften",  # no word boundary
        "A shares in Shanghai close mixed after policy note",  # len < 2 excluded
    ):
        verdict = _evaluate(
            {
                "title": title,
                "language": "English",
                "seendate": "20260918T090000Z",
                "url": "https://www.example.com/a",
                "domain": "example.com",
            }
        )
        assert verdict == (), title


def test_spaced_punctuation_alias_survives() -> None:
    verdict = _evaluate(
        {
            "title": "Hong Kong Hang Seng Index closes 1 . 18 pct higher",
            "language": "English",
            "seendate": "20260921T101500Z",
            "url": "https://www.bignewsnetwork.com/news/a",
            "domain": "bignewsnetwork.com",
        }
    )
    # official phrase evidence present; aggregator tier keeps score < tau
    assert "HSI.INDX" not in verdict


def test_spaced_punctuation_official_phrase_on_tier_a() -> None:
    verdict = _evaluate(
        {
            "title": "Hang Seng Index closes 1 . 18 pct higher",
            "language": "English",
            "seendate": "20260921T101500Z",
            "url": "https://www.scmp.com/news/a",
            "domain": "scmp.com",
        }
    )
    assert "HSI.INDX" in verdict


# ---- S3: dedup keys -----------------------------------------------------------


def test_dedup_key_a_url_normalization() -> None:
    base = normalize_url("https://www.reuters.com/article/apple-results/")
    variants = (
        "http://reuters.com/article/apple-results",
        "https://m.reuters.com/article/apple-results/",
        "https://www.reuters.com/article/apple-results?utm_source=feed&utm_medium=rss",
        "https://www.reuters.com/article/apple-results?utm_campaign=x&id=7",
        "https://www.reuters.com/article/apple-results?id=7",
    )
    assert base == "reuters.com/article/apple-results"
    for variant in variants[:3]:
        assert normalize_url(variant) == base, variant
    # non-utm params survive, sorted and stable
    assert normalize_url(variants[3]) == normalize_url(variants[4]) == base + "?id=7"


def test_dedup_key_b_jaccard_boundary() -> None:
    a = title_token_set("Tencent wins approval for two mobile game titles in September")
    b = title_token_set("Tencent wins approval for two mobile game titles in August")
    c = title_token_set("Regulator approves two mobile game titles for Tencent unit")
    assert jaccard(a, b) == pytest.approx(9 / 11)
    assert jaccard(a, b) >= 0.8  # duplicate class
    assert jaccard(a, c) < 0.8  # distinct


def test_survivor_total_order() -> None:
    low_tier_early = {"source_tier": 0.3, "seendate": "20260915T090000Z", "id": 1}
    high_tier_late = {"source_tier": 1.0, "seendate": "20260917T090000Z", "id": 2}
    high_tier_earlier = {"source_tier": 1.0, "seendate": "20260916T090000Z", "id": 3}
    assert pick_survivor([low_tier_early, high_tier_late, high_tier_earlier])["id"] == 3
    assert pick_survivor([high_tier_late, low_tier_early])["id"] == 2
    with pytest.raises(ValueError):
        pick_survivor(
            [
                {"source_tier": 1.0, "seendate": "20260916T090000Z", "id": 4},
                {"source_tier": 1.0, "seendate": "20260916T090000Z", "id": 5},
            ]
        )


# ---- fixture corpus + precision gate (QA-002) ---------------------------------


def _corpus() -> list[dict]:
    data = json.loads(CORPUS_PATH.read_text(encoding="ascii"))
    return list(data["items"])


def test_fixture_corpus_shape() -> None:
    items = _corpus()
    assert len(items) == 200
    for item in items:
        assert item["class"] in _KNOWN_CLASSES, item["class"]
        assert item["label"] in {"keep", "reject"}
        assert isinstance(item["title"], (str, type(None)))


def test_fixture_precision_gate() -> None:
    items = _corpus()
    tp = fp = fn = tn = 0
    for item in items:
        kept = bool(_evaluate(item))
        if kept and item["label"] == "keep":
            tp += 1
        elif kept and item["label"] == "reject":
            fp += 1
        elif not kept and item["label"] == "keep":
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    # FR-003 fit criterion: keep-decision precision >= 0.8 (tau = 1.0, D2).
    # Remaining false positives are the documented adversarial classes
    # (word-collision tickers on unknown domains; macro keyword groups
    # matching history/geography uses) — calibration evidence for QA-002.
    assert precision >= 0.8, f"precision={precision:.3f} fp={fp}"
    assert tp + fp + fn + tn == len(items)  # corpus fully exercised
    assert recall >= 0.9  # recorded and sanity-floored (not the gate)
