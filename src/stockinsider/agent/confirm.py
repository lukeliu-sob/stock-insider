"""One-time human confirmation tokens for write tools (H3, INV-004).

The model proposes; the human confirms through the harness. A
write-class tool call from the conversational loop never executes
on the model\'s say-so — the engine issues a single-use token bound
to (session, tool, arguments), the REPL collects the human\'s
reply, and only the consumed-token replay path executes with
allow_write=True. The boolean the model used to fill is gone from
every write tool spec.

Implements: REQ-SI-INV-004, REQ-SI-FR-004 (ADR-005 Am1; TP-017 PR-2)
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any


@dataclass
class PendingWrite:
    """One issued confirmation request.

    Implements: REQ-SI-INV-004 (ADR-005 Am1)
    """

    session_id: str
    tool: str
    arguments: dict[str, Any]
    turn: int = 0


class ConfirmationBroker:
    """Issues and consumes single-use confirmation tokens.

    Implements: REQ-SI-INV-004 (ADR-005 Am1; TP-017 PR-2)
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingWrite] = {}

    def issue(self, session_id: str, tool: str, arguments: dict[str, Any], turn: int = 0) -> str:
        """Create a pending write request; returns its one-time token.

        Implements: REQ-SI-INV-004 (ADR-005 Am1)
        """
        token = secrets.token_hex(4)
        self._pending[token] = PendingWrite(
            session_id=session_id, tool=tool, arguments=dict(arguments), turn=turn
        )
        return token

    def consume(self, token: str) -> PendingWrite | None:
        """Redeem a token exactly once; None when unknown/already used.

        Implements: REQ-SI-INV-004 (ADR-005 Am1)
        """
        return self._pending.pop(token, None)

    def expire_turns(self, current_turn: int, max_age: int = 3) -> None:
        """Drop stale requests so tokens cannot linger indefinitely.

        Implements: REQ-SI-INV-004 (ADR-005 Am1)
        """
        stale = [t for t, p in self._pending.items() if current_turn - p.turn > max_age]
        for token in stale:
            del self._pending[token]
