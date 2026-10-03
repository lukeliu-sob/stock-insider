"""TP-026: DE-10(d), tool-call arguments are not citable evidence.

Implements: REQ-SI-INV-001 (DE-10)
"""

from __future__ import annotations

import pathlib

import yaml

from stockinsider.agent import guardrail

IDENTITY_PATH = pathlib.Path(__file__).resolve().parents[2] / "prompts" / "identity.md"


def test_identity_prompt_names_arguments_as_not_citable() -> None:
    text = IDENTITY_PATH.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(text.split("---")[1])
    assert frontmatter["version"] == 7
    flat = " ".join(text.split())  # tolerate the file's own line-wrapping
    assert "Tool-call arguments are not evidence" in flat
    assert "is not a stored value" in flat
    # the new rule sits right after the existing citable-evidence rule
    numbers_rule = text.index("Numbers come from tools")
    arguments_rule = text.index("Tool-call arguments are not evidence")
    render_rule = text.index("Numbers render as returned")
    assert numbers_rule < arguments_rule < render_rule


def test_model_citing_request_arguments_fails_postcheck() -> None:
    """Even if the prompt rule were ignored, the ledger never carries request
    arguments, so the existing INV-001 post-check catches the citation too -
    the prompt rule is reinforced by the guardrail, not the only line of
    defense (TP-026 fit criterion)."""
    ledger = {
        "turn-0001/news.recent#1": {
            "symbol": "0700.HK",
            "items": [{"title": "a"}, {"title": "b"}, {"title": "c"}, {"title": "d"}],
        }
    }
    candidate = "I asked for 10 but only 4 headlines came back."
    check = guardrail.postcheck_numbers(candidate, ledger)
    claims = {c.surface: c.verified for c in check.claims}
    assert claims["4"] is True  # the returned count verifies against the list length
    assert claims["10"] is False  # the requested count (a tool-call argument) never verifies
