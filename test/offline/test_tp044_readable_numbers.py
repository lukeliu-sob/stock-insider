"""TP-044: identity v8 lets the model write a fraction as a two-decimal percent.

The renderings the rule allows must all pass the post-check, so the prompt never invites a
`[?]`; wrong renderings stay flagged. Runs on the frozen E-015 ledgers (real tool shapes).

Implements: REQ-SI-INV-001, REQ-SI-QA-001 (ADR-008 decision 2; TP-044)
"""

from __future__ import annotations

from test_tp025_stage5_e013 import _specs
from test_tp042_live_false_flags import BYD, PERF

from stockinsider.agent import guardrail
from stockinsider.agent.loop import load_identity_prompt

VOLATILITY = BYD["turn-0001/market.indicators#2"]["risk"]["volatility"]["value"]
DRAWDOWN = BYD["turn-0001/market.indicators#2"]["risk"]["max_drawdown"]["value"]
MONTH = next(row for row in PERF["turn-0001/market.performance#3"]["windows"] if row["sessions"] == 20)


def _verdicts(text: str, ledger: dict) -> dict[str, bool]:
    return {claim.raw: claim.verified for claim in guardrail.postcheck_numbers(text, ledger, _specs()).claims}


def test_identity_prompt_is_v8_with_readable_rule() -> None:
    version, body = load_identity_prompt()
    assert version == "identity-v8"
    flat = " ".join(body.split())
    assert "Numbers render as returned, readably." in flat
    assert "a fraction may be written as a percent with two decimals" in flat
    assert "Prices, volumes, counts and dates appear exactly as received" in flat
    assert "Never add precision" in flat
    assert flat.index("Tool-call arguments are not evidence") < flat.index("Numbers render as returned")


def test_rule_renderings_verify() -> None:
    pct, short = f"{VOLATILITY * 100:.2f}", f"{VOLATILITY:.4f}"
    drawdown = f"{DRAWDOWN * 100:.2f}"
    month = f"{MONTH['change_pct']:.2f}"
    texts = [
        (f"BYD's annualized volatility is {pct}% and its max drawdown {drawdown}%.", BYD),
        (f"BYD's annualized volatility reads {short}.", BYD),
        (f"Tencent's 20-session change is {month}%.", PERF),
        (f"Tencent fell {abs(MONTH['change_pct']):.2f}% over the last 20 sessions.", PERF),
    ]
    for text, ledger in texts:
        assert all(_verdicts(text, ledger).values()), (text, _verdicts(text, ledger))


def test_wrong_renderings_are_still_flagged() -> None:
    assert f"{VOLATILITY * 100:.2f}" == "8.85"  # the frozen ledger's value, so the cases below are wrong
    assert not _verdicts("BYD's annualized volatility is 8.58%.", BYD)["8.58"]  # digits transposed
    assert not _verdicts("BYD's annualized volatility is 0.09%.", BYD)["0.09"]  # the fraction read as a percent
    week = next(row for row in PERF["turn-0001/market.performance#3"]["windows"] if row["sessions"] == 5)
    given = f"{week['change_pct']:.2f}"
    assert not _verdicts(f"Tencent rose {given}% over the last 20 sessions.", PERF)[given]  # the 5-session change
