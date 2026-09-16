"""Offline tests for analysis profiles and budget envelopes (TP-002, FR-020).

Fit criteria: two profiles yield differing profile fields and budget
envelopes; mid-session profile switching is an explicit error; budget
boundaries hold at bound and bound ±1 (verification rule R8).
"""

import pytest

from stockinsider.agent.context import (
    ContextAssembler,
    ContextBudgetError,
    ContextLayerError,
    CONTEXT_LAYERS,
)
from stockinsider.agent.profiles import Profile, envelope_for, within_budget
from stockinsider.agent.session import SessionError, SessionStore


def test_two_profiles_differ_in_fields_and_budget(tmp_path) -> None:
    store = SessionStore(root=tmp_path / "sessions")
    quick = store.create(profile="quick")
    deep = store.create(profile="deep")
    assert quick["profile"] != deep["profile"]
    assert envelope_for("quick").max_session_tokens != envelope_for("deep").max_session_tokens


@pytest.mark.parametrize(
    ("profile", "used", "expected"),
    [
        ("quick", 29_999, True),
        ("quick", 30_000, True),
        ("quick", 30_001, False),
        ("standard", 99_999, True),
        ("standard", 100_000, True),
        ("standard", 100_001, False),
        ("deep", 399_999, True),
        ("deep", 400_000, True),
        ("deep", 400_001, False),
    ],
)
def test_budget_boundaries(profile: str, used: int, expected: bool) -> None:
    assert within_budget(profile, used) is expected


def test_mid_session_profile_switch_is_explicit_error(tmp_path) -> None:
    store = SessionStore(root=tmp_path / "sessions")
    record = store.create(profile="quick")
    with pytest.raises(SessionError, match="fixed for the session lifetime"):
        store.resume(record["session_id"], profile="deep")


def test_assembler_orders_layers_and_fits() -> None:
    assembler = ContextAssembler("quick")
    parts = {
        "current-task": "tail content",
        "identity": "head content",
        "standing-constraints": "middle content",
    }
    assembled = assembler.assemble(parts)
    assert assembled.index("head content") < assembled.index("middle content") < assembled.index("tail content")


def test_assembler_overflow_aborts_explicitly() -> None:
    assembler = ContextAssembler("quick")
    parts = {CONTEXT_LAYERS[0]: "x" * 200_000}  # ~50k tokens > 30k quick envelope
    with pytest.raises(ContextBudgetError, match="explicit abort"):
        assembler.assemble(parts)


def test_assembler_rejects_unknown_layer() -> None:
    assembler = ContextAssembler("quick")
    with pytest.raises(ContextLayerError, match="unknown context layer"):
        assembler.assemble({"mystery-layer": "content"})


def test_profile_enum_members() -> None:
    assert {p.value for p in Profile} == {"quick", "standard", "deep"}
