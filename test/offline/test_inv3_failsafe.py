"""Offline fault-injection tests for the tool registry (TP-005).

INV-003 fail-closed matrix at the membrane: unknown tools, schema
violations, handler exceptions, write-effect gating, and the provenance
triple on success (INV-001 groundwork). SEC-002 argument hardening.
"""

import pytest

from stockinsider.agent.registry import Registry, RegistryError
from stockinsider.shared.tools import (
    EffectClass,
    SourceKind,
    ToolCall,
    ToolSpec,
    ToolWireError,
    validate_arguments,
)


def make_spec(
    name: str = "demo.add",
    effect: EffectClass = EffectClass.COMPUTE,
    arguments_spec: dict[str, str] | None = None,
    result_spec: str = "dict",
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="demo tool",
        arguments_spec=arguments_spec if arguments_spec is not None else {"a": "int", "b": "int"},
        optional_spec={},
        result_spec=result_spec,
        effect_class=effect,
        source_kind=SourceKind.COMPUTED,
    )


def make_registry(spec: ToolSpec, handler) -> Registry:
    registry = Registry()
    registry.register(spec, handler)
    return registry


def test_unknown_tool_refused() -> None:
    registry = make_registry(make_spec(), lambda args: {"sum": args["a"] + args["b"]})
    result = registry.execute(ToolCall(tool="nope.delete", arguments={}, call_id="c1"))
    assert result.ok is False
    assert "unknown tool" in result.error
    assert result.result is None


def test_unknown_argument_refused() -> None:
    registry = make_registry(make_spec(), lambda args: {"sum": args["a"] + args["b"]})
    result = registry.execute(ToolCall(tool="demo.add", arguments={"a": 1, "b": 2, "x": 3}, call_id="c2"))
    assert result.ok is False and "unknown argument" in result.error


def test_missing_required_argument_refused() -> None:
    registry = make_registry(make_spec(), lambda args: {"sum": args["a"] + args["b"]})
    result = registry.execute(ToolCall(tool="demo.add", arguments={"a": 1}, call_id="c3"))
    assert result.ok is False and "missing required argument" in result.error


def test_argument_type_mismatch_refused() -> None:
    registry = make_registry(make_spec(), lambda args: {"sum": args["a"] + args["b"]})
    result = registry.execute(ToolCall(tool="demo.add", arguments={"a": "one", "b": 2}, call_id="c4"))
    assert result.ok is False and "must be int" in result.error


def test_bool_not_accepted_as_int() -> None:
    registry = make_registry(make_spec(), lambda args: {"sum": args["a"] + args["b"]})
    result = registry.execute(ToolCall(tool="demo.add", arguments={"a": True, "b": 1}, call_id="c5"))
    assert result.ok is False and "got bool" in result.error


def test_handler_exception_is_explicit_failure() -> None:
    def boom(_args):
        raise ValueError("disk exploded")

    registry = make_registry(make_spec(), boom)
    result = registry.execute(ToolCall(tool="demo.add", arguments={"a": 1, "b": 2}, call_id="c6"))
    assert result.ok is False
    assert "failed: ValueError: disk exploded" in result.error
    assert result.result is None  # never a partial result


def test_result_type_mismatch_refused() -> None:
    registry = make_registry(make_spec(result_spec="dict"), lambda args: "not-a-dict")
    result = registry.execute(ToolCall(tool="demo.add", arguments={"a": 1, "b": 2}, call_id="c7"))
    assert result.ok is False and "result of tool" in result.error


def test_write_effect_gated_from_user_channel() -> None:
    calls = []

    def handler(args):
        calls.append(args)
        return {"deleted": True}

    registry = make_registry(make_spec(name="demo.purge", effect=EffectClass.WRITE), handler)
    blocked = registry.execute(ToolCall(tool="demo.purge", arguments={"a": 1, "b": 2}, call_id="c8"))
    assert blocked.ok is False and "write effects" in blocked.error
    assert calls == []  # handler never ran
    allowed = registry.execute(ToolCall(tool="demo.purge", arguments={"a": 1, "b": 2}, call_id="c9"), allow_write=True)
    assert allowed.ok is True  # the gate, not the tool, decides


def test_successful_result_carries_provenance_triple() -> None:
    registry = make_registry(make_spec(), lambda args: {"sum": args["a"] + args["b"]})
    result = registry.execute(ToolCall(tool="demo.add", arguments={"a": 20, "b": 22}, call_id="c10"))
    assert result.ok is True
    assert result.result == {"sum": 42}
    assert set(result.provenance) == {"tool", "source_kind", "produced_at"}
    assert result.provenance["tool"] == "demo.add"
    assert result.provenance["source_kind"] == "computed"
    assert "T" in result.provenance["produced_at"]


def test_duplicate_registration_refused() -> None:
    registry = make_registry(make_spec(), lambda args: {})
    with pytest.raises(RegistryError, match="already registered"):
        registry.register(make_spec(), lambda args: {})


def test_validate_arguments_rejects_non_object() -> None:
    with pytest.raises(ToolWireError, match="must be an object"):
        validate_arguments(make_spec(), ["not", "a", "dict"])


def test_list_tools_sorted_by_name() -> None:
    registry = make_registry(make_spec(name="zeta.tool"), lambda args: {})
    registry.register(make_spec(name="alpha.tool"), lambda args: {})
    assert [spec.name for spec in registry.list_tools()] == ["alpha.tool", "zeta.tool"]
