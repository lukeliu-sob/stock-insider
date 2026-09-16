"""Live evaluation-set replay — the semantic evaluation gate body (D7-4).

QA-001 seed level: provider-behavior cases that validate the model
routing and endpoint end-to-end. The report-level faithfulness replay
(retrieval-augmented answers) extends this set when the agent analysis
loop lands; until then this file honestly covers what exists.

Never part of the offline suite. Inside the CI eval gate it must never
silently skip: without a configured provider it fails explicitly.
Local opt-out for offline development: STOCKINSIDER_ALLOW_LIVE_SKIP=1.

Implements: REQ-SI-QA-001 (seed level) (ADR-001)
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable

import pytest

from stockinsider.agent.providers import (
    OpenAICompatibleProvider,
    resolve_api_key,
    resolve_config,
)

#: QA-001 faithfulness threshold (pass rate over the evaluation set).
EVAL_THRESHOLD = 0.6


def _provider() -> OpenAICompatibleProvider:
    """Resolve the provider; explicit failure instead of silent skipping.

    Implements: REQ-SI-QA-001 (ADR-001)
    """
    config = resolve_config()
    key, _source = resolve_api_key()
    allow_skip = os.environ.get("STOCKINSIDER_ALLOW_LIVE_SKIP") == "1"
    if allow_skip:
        pytest.skip("live evaluation skipped by explicit local opt-out (STOCKINSIDER_ALLOW_LIVE_SKIP=1)")
    if not config.chat_base_url:
        pytest.fail(
            "chat base_url unconfigured — the evaluation gate refuses to run blind "
            "(set it via config or PROVIDER_BASE_URL; INV-003)"
        )
    if key is None:
        pytest.fail(
            "PROVIDER_API_KEY not set — evaluation replay must not silently skip "
            "(set the key, or STOCKINSIDER_ALLOW_LIVE_SKIP=1 for local offline work)"
        )
    return OpenAICompatibleProvider(config, api_key=key)


def _check_exact_echo(response: str) -> bool:
    return "ACK-7749" in response


def _check_json_only(response: str) -> bool:
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if not match:
        return False
    try:
        return json.loads(match.group(0)) == {"ok": True}
    except json.JSONDecodeError:
        return False


def _check_english_only(response: str) -> bool:
    return bool(re.search(r"[A-Za-z]", response)) and not re.search(r"[\u4e00-\u9fff]", response)


def _check_yes_no(response: str) -> bool:
    return response.strip().rstrip(".").lower() in {"yes", "no"}


def _check_short_confirmation(response: str) -> bool:
    sentences = [s for s in re.split(r"[.!?]", response) if s.strip()]
    return 0 < len(sentences) <= 2


#: (name, prompt, checker) — the seed evaluation set.
CASES: list[tuple[str, str, Callable[[str], bool]]] = [
    (
        "exact-echo",
        "Reply with exactly this token and nothing else: ACK-7749",
        _check_exact_echo,
    ),
    (
        "json-only",
        'Return only this JSON object and nothing else: {"ok": true}',
        _check_json_only,
    ),
    (
        "english-only",
        "Answer in exactly one English sentence: what is two plus two?",
        _check_english_only,
    ),
    (
        "yes-no-stability",
        "Answer with a single word: yes or no. Is water wet?",
        _check_yes_no,
    ),
    (
        "short-confirmation",
        "Reply with one short sentence confirming you received this message.",
        _check_short_confirmation,
    ),
]


def test_evaluation_set_pass_rate() -> None:
    """Replay the evaluation set; pass rate must meet the QA-001 threshold.

    Implements: REQ-SI-QA-001 (ADR-001)
    """
    provider = _provider()
    by_name = {name: (prompt, checker) for name, prompt, checker in CASES}
    results: list[tuple[str, bool, str]] = []
    for name, prompt, checker in CASES:
        response, _usage = provider.chat([{"role": "user", "content": prompt}])
        results.append((name, checker(response), response.strip()[:80]))
    # Stability case runs twice by design (same prompt, both must pass).
    prompt, checker = by_name["yes-no-stability"]
    response, _usage = provider.chat([{"role": "user", "content": prompt}])
    results.append(("yes-no-stability-2nd", checker(response), response.strip()[:80]))
    passed = sum(1 for _name, ok, _ in results if ok)
    rate = passed / len(results)
    report = "\n".join(f"  {'PASS' if ok else 'FAIL'} {name}: {excerpt!r}" for name, ok, excerpt in results)
    print(f"evaluation-set replay: {passed}/{len(results)} passed (rate {rate:.2f}, threshold {EVAL_THRESHOLD})")
    print(report)
    assert rate >= EVAL_THRESHOLD, (
        f"evaluation-set pass rate {rate:.2f} below threshold {EVAL_THRESHOLD} (QA-001)\n{report}"
    )


def test_provider_usage_reported() -> None:
    """The provider returns usage alongside content (COST-002 groundwork).

    Implements: REQ-SI-COST-002 (ADR-001)
    """
    provider = _provider()
    _text, usage = provider.chat([{"role": "user", "content": "Reply with: ok"}])
    assert isinstance(usage, dict)
    assert "prompt_tokens" in usage, "usage missing prompt_tokens (COST-002 interface)"
