"""Offline tests for the runtime language-policy helpers (TP-004, FR-014/GOV-001).

The CI artifact gate stays authoritative for repository files; these
tests cover the runtime helpers future render paths will call.
"""

import pytest

from stockinsider.shared.language import (
    CJK_PATTERN,
    LanguagePolicyError,
    assert_english,
    is_english_only,
)


def test_pure_english_passes() -> None:
    assert is_english_only("The quick brown fox jumps over the lazy dog.")
    assert_english("plain ascii, digits 123, and punctuation!")


def test_pure_cjk_rejected() -> None:
    assert not is_english_only("腾讯控股")


def test_mixed_script_rejected() -> None:
    assert not is_english_only("Tencent 腾讯控股")


def test_cjk_punctuation_rejected() -> None:
    assert not is_english_only("Hello！")


def test_fullwidth_forms_rejected() -> None:
    assert not is_english_only("（note）")


def test_assert_english_raises_with_context() -> None:
    with pytest.raises(LanguagePolicyError, match="render path"):
        assert_english("价格上涨", context="render path")


def test_assert_english_names_the_offending_character() -> None:
    with pytest.raises(LanguagePolicyError, match="GOV-001"):
        assert_english("price 价")


def test_pattern_covers_ideographs_punctuation_fullwidth() -> None:
    assert CJK_PATTERN.search("价")
    assert CJK_PATTERN.search("。")
    assert CJK_PATTERN.search("）")
    assert not CJK_PATTERN.search("aZ09 .,!?()-")
