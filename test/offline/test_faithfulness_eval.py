"""TP-016 PR-epsilon: guardrail faithfulness, measured (review finding 6).

QA-001's faithfulness property, made falsifiable at the unit level:
a labeled suite of good citations (must pass the post-check) and
fabrications (must be quarantined) yields precision and recall for
the numeric-provenance checker itself. The known residual classes
(prose years, integer percents, window words, time-of-day
renderings, identifier fragments) are counted separately - they
are recorded in the evaluation logbook and parked for the owner
extraction-semantics decision; they are NOT silently excused from
the denominators nor allowed to fail the gate.

Implements: REQ-SI-QA-001, REQ-SI-INV-001 (ADR-006)
"""

from __future__ import annotations

from stockinsider.agent.guardrail import postcheck_numbers

POOL = {
    "market.quote#1": {
        "symbol": "0700.HK",
        "date": "2026-09-25",
        "close": 436.6,
        "adjusted_close": 436.6,
        "volume": 9110000,
    },
    "market.quote#2": {"symbol": "1211.HK", "close": 77.7, "date": "2026-09-25"},
    "market.indicators#1": {"risk": {"volatility": 0.4528}},
    "news.recent#1": {"items": [{"seendate": "20260923T183300Z", "title": "T"}]},
    "market.quote#3": {"close": 439.8, "date": "2026-09-24"},
}

GOOD = [
    ("exact close", "0700.HK closed at 436.6"),
    ("two-tool cites", "0700.HK 436.6 while 1211.HK 77.7"),
    ("display rounding in window", "closed at 436.60"),
    ("percent with marker", "volatility of about 45.28%"),
    ("iso date", "reported on 2026-09-25"),
    ("compact date", "reported on 20260925"),
    ("volume", "volume 9110000 shares"),
]
BAD = [
    ("fabricated close", "0700.HK closed at 436.7"),
    ("off-by-one-class", "0700.HK closed at 437"),
    ("wrong date", "reported on 2026-09-26"),
    ("wrong percent no marker", "volatility of about 45.28"),
    ("invented number", "peaked at 500.0"),
    ("percent without marker", "volatility 45"),
]
RESIDUAL = [
    ("prose year", "between October 2025 and June 2026"),
    ("integer percent", "volatility of about 45%"),
    ("window word", "over the last 20 sessions"),
    ("time of day", "at 14:05:09 that day"),
]


def test_faithfulness_precision() -> None:
    """Every good citation passes (zero false quarantines)."""
    quarantined = [
        name for name, text in GOOD if not postcheck_numbers(text, POOL).passed
    ]
    assert not quarantined, f"false quarantines: {quarantined}"


def test_faithfulness_recall() -> None:
    """Every fabrication is quarantined (zero escapes)."""
    escaped = [name for name, text in BAD if postcheck_numbers(text, POOL).passed]
    assert not escaped, f"fabrications escaped: {escaped}"


def test_residual_classes_reported_not_hidden() -> None:
    """Residuals fail today; they are counted and pinned by name.

    This test documents the current truth (they quarantine) and the
    count; when the owner extraction-semantics decision lands, the
    affected labels move to GOOD and this test changes with it -
    never before.
    """
    still_failing = [name for name, text in RESIDUAL if not postcheck_numbers(text, POOL).passed]
    assert still_failing == [
        "prose year",
        "integer percent",
        "window word",
        "time of day",
    ], "residual set changed - update the logbook record with this PR"
