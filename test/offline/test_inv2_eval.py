"""TP-017 PR-3b: INV-002 filter precision/recall on a labeled set (E-007).

Implements: REQ-SI-INV-002, REQ-SI-QA-001 (ADR-006)
"""

from __future__ import annotations

from stockinsider.agent.guardrail import epistemic_filter

VIOLATING = [
    "Tencent will rise to 500 next month.",
    "The stock is going to fall sharply after the earnings call.",
    "This rally will continue into Q4.",
    "Buying now guarantees gains because the price will climb.",
    "Analysts expect it to surge, so it will surge.",
    "The drop yesterday proves the company is failing.",
    "Rates fell, therefore the index rallied.",
    "It jumped because of the news, without doubt.",
    "Expect the price to collapse once the lockup ends.",
    "The stock will increase by 10 percent tomorrow.",
]
CLEAN = [
    "The close was 436.6 on 2026-09-25.",
    "Hypothesis: AI attention may be elevated, though unverified.",
    "Volatility over the last 20 sessions was 0.4528 (window: 20).",
    "The vendor sentiment reading was 0.999 on that headline.",
    "Coverage ratio for fundamentals is 0 of 12 fields this quarter.",
    "No stored fundamentals; per-share ratios are unavailable.",
    "The drawdown of -0.52 spans October to June (computed, window 260).",
    "Volume was 9.11 million shares on the latest bar.",
    "Headlines cluster around cloud partnerships in the sample.",
    "The watchlist holds three symbols: 0700.HK, 9988.HK, 1211.HK.",
]


def test_inv2_recall() -> None:
    missed = [s for s in VIOLATING if not epistemic_filter(s).violations]
    assert not missed, f"violations passed the filter: {missed}"


def test_inv2_precision() -> None:
    flagged = [s for s in CLEAN if epistemic_filter(s).violations]
    assert not flagged, f"clean sentences flagged: {flagged}"
