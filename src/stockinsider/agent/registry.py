"""Tool registry: the authority membrane (blueprint §4.1, §9.1).

The LLM never touches storage, network, or computation directly; every
access flows through registered tools with validated schemas, gated
effect classes, and provenance-stamped results. Handlers are injected
by the composition layer — this module imports only shared, preserving
the dependency law (agent/registry -> shared + later the data facade).

Implements: REQ-SI-INV-003, REQ-SI-INV-001, REQ-SI-SEC-002 (ADR-005)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from stockinsider.shared.tools import (
    EffectClass,
    ToolCall,
    ToolResult,
    ToolSpec,
    ToolWireError,
    validate_arguments,
    validate_result_payload,
)


class RegistryError(RuntimeError):
    """Explicit registration-level failure (duplicate names, bad state).

    Implements: REQ-SI-INV-003 (ADR-005)
    """


class Registry:
    """Tool registration and fail-closed execution envelope.

    Implements: REQ-SI-INV-003, REQ-SI-INV-001 (ADR-005)
    """

    def __init__(self) -> None:
        """Start with an empty registration table."""
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def register(self, spec: ToolSpec, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Register a tool; duplicate names are refused explicitly.

        Implements: REQ-SI-INV-003 (ADR-005)
        """
        if spec.name in self._specs:
            raise RegistryError(f"tool {spec.name!r} is already registered")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def list_tools(self) -> list[ToolSpec]:
        """Return all registered specs, sorted by name.

        Implements: REQ-SI-FR-013 (ADR-005)
        """
        return sorted(self._specs.values(), key=lambda spec: spec.name)

    def execute(self, call: ToolCall, *, allow_write: bool = False) -> ToolResult:
        """Execute one validated tool call; every failure is explicit.

        Fail-closed order: unknown tool -> write gate -> argument
        validation -> handler execution -> result validation. Handler
        exceptions become ok=False results — never partial results,
        never swallowed errors (INV-003). Successful results carry the
        provenance triple {tool, source_kind, produced_at} (INV-001
        groundwork).

        Implements: REQ-SI-INV-003, REQ-SI-INV-001 (ADR-005)
        """
        spec = self._specs.get(call.tool)
        if spec is None:
            return ToolResult(
                call_id=call.call_id,
                ok=False,
                error=f"unknown tool {call.tool!r}; registered: {sorted(self._specs)}",
            )
        if spec.effect_class is EffectClass.WRITE and not allow_write:
            return ToolResult(
                call_id=call.call_id,
                ok=False,
                error=(
                    f"tool {spec.name!r} has write effects; write tools require the "
                    "conversational confirmation flow or a CLI subcommand (blueprint §9.1)"
                ),
            )
        try:
            validate_arguments(spec, call.arguments)
        except ToolWireError as exc:
            return ToolResult(call_id=call.call_id, ok=False, error=str(exc))
        try:
            payload = self._handlers[spec.name](dict(call.arguments))
        except Exception as exc:  # noqa: BLE001 — surfaced, never swallowed
            return ToolResult(
                call_id=call.call_id,
                ok=False,
                error=f"tool {spec.name!r} failed: {type(exc).__name__}: {exc}",
            )
        try:
            validate_result_payload(spec, payload)
        except ToolWireError as exc:
            return ToolResult(call_id=call.call_id, ok=False, error=str(exc))
        return ToolResult(
            call_id=call.call_id,
            ok=True,
            result=payload,
            provenance={
                "tool": spec.name,
                "source_kind": spec.source_kind.value,
                "produced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
