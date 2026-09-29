"""TP-016 PR-gamma: registry/facade boundary source invariants (finding 2).

Implements: REQ-SI-GOV-006 (ADR-005 Amendment 1)
"""

from __future__ import annotations

import re
from pathlib import Path

REGISTRY = (
    Path(__file__).resolve().parents[2] / "src" / "stockinsider" / "agent" / "registry.py"
)


def test_registry_has_no_data_internal_imports() -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    offenders = re.findall(r"^.*from stockinsider\.data\.[^\s]+.*$", text, re.M)
    assert not offenders, f"registry imports data internals: {offenders}"


def test_registry_has_no_direct_store_connection() -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    offenders = [ln for ln in text.splitlines() if ".conn" in ln]
    assert not offenders, f"registry touches the store connection directly: {offenders}"


def test_registry_has_no_inline_sql() -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    offenders = [ln for ln in text.splitlines() if "SELECT " in ln or "INSERT " in ln]
    assert not offenders, f"registry carries inline SQL: {offenders}"


def test_facade_methods_exist() -> None:
    from stockinsider.data.store import DataStore

    for name in (
        "market_quote",
        "fundamentals_coverage",
        "news_recent_rows",
        "market_indicators_snapshot",
    ):
        assert callable(getattr(DataStore, name, None)), name
