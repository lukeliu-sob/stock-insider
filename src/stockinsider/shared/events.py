"""Session event schema (FR-011): authoritative kinds and fail-closed validation.

session.jsonl events are validated against this module's EventKind
enum; the shapes already on disk from TP-002/TP-003 are the authority
this module describes (validate the existing form, not a new one).
Schema evolution is forward-only (memory-design S6; ADR-004).

Implements: REQ-SI-FR-011 (ADR-004)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from stockinsider.shared.provenance import validate_provenance


class EventKind(str, Enum):
    """Authoritative session.jsonl event kinds (forward-only evolution).

    Implements: REQ-SI-FR-011 (ADR-004)
    """

    SESSION_OPEN = "session-open"
    USER_MESSAGE = "user-message"
    ASSISTANT_MESSAGE = "assistant-message"
    TOOL_CALL = "tool-call"
    TOOL_RESULT = "tool-result"
    ERROR = "error"
    SESSION_CLOSE = "session-close"


class EventValidationError(RuntimeError):
    """Explicit session-event rejection (FR-011, fail-closed).

    Implements: REQ-SI-FR-011 (ADR-004)
    """


def validate_event(event: Any) -> None:
    """Validate one session.jsonl event; unknown shapes fail closed.

    Implements: REQ-SI-FR-011 (ADR-004)
    """
    if not isinstance(event, dict):
        raise EventValidationError(f"event must be a JSON object, got {type(event).__name__}")
    kind = event.get("event")
    if not isinstance(kind, str) or not kind.strip():
        raise EventValidationError("event missing the 'event' kind field")
    try:
        parsed = EventKind(kind)
    except ValueError:
        raise EventValidationError(
            f"unknown event kind {kind!r}; allowed: {[k.value for k in EventKind]} (forward-only schema, ADR-004)"
        ) from None
    if parsed is EventKind.SESSION_OPEN:
        record = event.get("record")
        if not isinstance(record, dict):
            raise EventValidationError("session-open event requires a 'record' object")
        provenance = record.get("provenance")
        if not isinstance(provenance, dict):
            raise EventValidationError("session-open record requires a 'provenance' mapping")
        validate_provenance(provenance)
