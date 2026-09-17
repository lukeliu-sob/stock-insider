"""Tool wire envelopes and validation (the registry membrane's format).

ToolSpec / ToolCall / ToolResult are the authoritative wire types for
every tool interaction; validation is fail-closed (unknown fields,
missing required fields, and type mismatches are explicit errors).
Hand-written validators per ADR-004's pydantic deferral.

Implements: REQ-SI-INV-003, REQ-SI-SEC-002 (ADR-005)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SourceKind(str, Enum):
    """Provenance stamp classes for tool outputs (blueprint §4.1).

    Implements: REQ-SI-INV-001 (ADR-005)
    """

    API = "api"
    CRAWLED = "crawled"
    COMPUTED = "computed"
    MODEL_JUDGMENT = "model-judgment"


class EffectClass(str, Enum):
    """Tool effect classes; write effects are gated (blueprint §9.1).

    Implements: REQ-SI-INV-003 (ADR-005)
    """

    READ = "read"
    COMPUTE = "compute"
    WRITE = "write"


#: JSON-Schema type names for the wire types (OpenAI tool parameters).
JSON_SCHEMA_TYPES: dict[str, str] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
}

#: Wire type names allowed in specs (str/int/float/bool/list/dict).
_WIRE_TYPES: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
}


class ToolWireError(RuntimeError):
    """Explicit tool-wire validation failure (fail-closed).

    Implements: REQ-SI-INV-003 (ADR-005)
    """


@dataclass(frozen=True)
class ToolSpec:
    """Immutable tool declaration: schemas, effect class, provenance rule.

    Implements: REQ-SI-SEC-002 (ADR-005)
    """

    name: str
    description: str
    arguments_spec: dict[str, str] = field(default_factory=dict)
    optional_spec: dict[str, str] = field(default_factory=dict)
    result_spec: str = "dict"
    effect_class: EffectClass = EffectClass.READ
    source_kind: SourceKind = SourceKind.COMPUTED


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation request (name, arguments, call id).

    Implements: REQ-SI-SEC-002 (ADR-005)
    """

    tool: str
    arguments: dict[str, Any]
    call_id: str


@dataclass(frozen=True)
class ToolResult:
    """One tool execution outcome; ok=False carries the explicit error.

    Implements: REQ-SI-INV-003 (ADR-005)
    """

    call_id: str
    ok: bool
    result: Any = None
    error: str | None = None
    provenance: dict[str, str] = field(default_factory=dict)


def _check_type(spec: ToolSpec, field_name: str, type_name: str, value: Any) -> None:
    expected = _WIRE_TYPES.get(type_name)
    if expected is None:
        raise ToolWireError(f"tool {spec.name!r} declares unknown wire type {type_name!r} for {field_name!r}")
    if expected is int and isinstance(value, bool):
        raise ToolWireError(f"argument {field_name!r} of tool {spec.name!r} must be int, got bool")
    if not isinstance(value, expected):
        raise ToolWireError(
            f"argument {field_name!r} of tool {spec.name!r} must be {type_name}, got {type(value).__name__}"
        )


def validate_arguments(spec: ToolSpec, arguments: Any) -> None:
    """Reject unknown fields, missing required fields, and type mismatches.

    Implements: REQ-SI-SEC-002 (ADR-005)
    """
    if not isinstance(arguments, dict):
        raise ToolWireError(f"arguments of tool {spec.name!r} must be an object, got {type(arguments).__name__}")
    allowed = set(spec.arguments_spec) | set(spec.optional_spec)
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ToolWireError(f"unknown argument(s) {unknown} for tool {spec.name!r}; allowed: {sorted(allowed)}")
    for field_name, type_name in spec.arguments_spec.items():
        if field_name not in arguments:
            raise ToolWireError(f"missing required argument {field_name!r} for tool {spec.name!r}")
        _check_type(spec, field_name, type_name, arguments[field_name])
    for field_name, type_name in spec.optional_spec.items():
        if field_name in arguments:
            _check_type(spec, field_name, type_name, arguments[field_name])


def validate_result_payload(spec: ToolSpec, payload: Any) -> None:
    """Reject result payloads whose top-level type breaks the declared spec.

    Implements: REQ-SI-INV-003 (ADR-005)
    """
    expected = _WIRE_TYPES.get(spec.result_spec)
    if expected is None:
        raise ToolWireError(f"tool {spec.name!r} declares unknown result type {spec.result_spec!r}")
    if not isinstance(payload, expected):
        raise ToolWireError(f"result of tool {spec.name!r} must be {spec.result_spec}, got {type(payload).__name__}")
