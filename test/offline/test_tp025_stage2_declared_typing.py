"""TP-025 stage 2: the guardrail's evidence typing consumes a tool's declared field semantics.

Stage 2 is behavior-neutral for tools that declare nothing (no tool declares fields before
stage 3), so the equivalence test is the main regression check. The other tests use synthetic
ToolSpecs and show that a declaration changes the typing of its own tool only.

Implements: REQ-SI-INV-001, REQ-SI-SEC-002 (ADR-005 Am4, ADR-008 phase 3; TP-025)
"""

from stockinsider.agent.guardrail_claims import check, index_evidence
from stockinsider.shared.tools import FieldSemantics, ToolSpec

PLAIN_SNAPSHOT = {"turn-0001/market.quote#1": {"symbol": "0700.HK", "close": 641.0, "currency": "HKD"}}
ANSWERS = [
    "Tencent closed at 641.0 HKD.",
    "Tencent closed at 999 HKD.",
    "Tencent is quoted at 641.0 HKD, and the close was 641.0 HKD.",
]


def declaring(name: str, **declarations) -> ToolSpec:
    return ToolSpec(name=name, description="synthetic test tool", **declarations)


def typed(snapshot: dict, specs: dict[str, ToolSpec] | None = None) -> list[tuple[float, str]]:
    return [(entry.value, entry.field) for entry in index_evidence(snapshot, specs).entries]


def test_equivalence_without_declarations() -> None:
    undeclared = {"market.quote": declaring("market.quote")}
    for answer in ANSWERS:
        without_specs, empty_specs, undeclared_specs = (
            check(answer, PLAIN_SNAPSHOT, specs) for specs in (None, {}, undeclared)
        )
        assert without_specs == empty_specs == undeclared_specs


def test_declared_direct_key_replaces_heuristic() -> None:
    snapshot = {"turn-0001/fake.quote#1": {"px_last": 644.63}}
    assert typed(snapshot) == [(644.63, "unknown")]
    specs = {"fake.quote": declaring("fake.quote", result_fields={"px_last": FieldSemantics("close")})}
    assert typed(snapshot, specs) == [(644.63, "close")]


def test_declared_key_rejects_a_mismatched_claim() -> None:
    snapshot = {"turn-0001/fake.quote#1": {"px_last": 644.63, "symbol": "0700.HK"}}
    answer = "The open price was 644.63 HKD."
    # an unknown key is compatible with any field, so the heuristic lets the open-price claim verify
    assert check(answer, snapshot).passed
    specs = {"fake.quote": declaring("fake.quote", result_fields={"px_last": FieldSemantics("close")})}
    verdict = check(answer, snapshot, specs)
    assert not verdict.passed
    assert "644.63" in verdict.failed


def test_discriminator_row_selects_declared_field() -> None:
    snapshot = {"turn-0001/fake.indicators#1": {"rows": [{"metric": "atr_14", "value": 3.2}]}}
    assert typed(snapshot) == [(3.2, "unknown")]
    specs = {
        "fake.indicators": declaring(
            "fake.indicators",
            result_discriminators={"metric": {"atr_14": FieldSemantics("atr")}},
        )
    }
    assert typed(snapshot, specs) == [(3.2, "atr")]


def test_declaration_does_not_leak_across_tools() -> None:
    snapshot = {
        "turn-0001/fake.a#1": {"px_last": 644.63},
        "turn-0001/fake.b#1": {"px_last": 12.0},
    }
    specs = {"fake.a": declaring("fake.a", result_fields={"px_last": FieldSemantics("close")})}
    assert sorted(typed(snapshot, specs)) == [(12.0, "unknown"), (644.63, "close")]


def test_undeclared_keys_keep_heuristic_under_declared_tool() -> None:
    snapshot = {"turn-0001/fake.a#1": {"px_last": 644.63, "open": 640.0}}
    specs = {"fake.a": declaring("fake.a", result_fields={"px_last": FieldSemantics("close")})}
    assert sorted(typed(snapshot, specs)) == [(640.0, "open"), (644.63, "close")]
