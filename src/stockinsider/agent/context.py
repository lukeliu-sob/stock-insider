"""Context assembly skeleton: six layers, budget envelope, explicit overflow.

Layer order per blueprint §8.1 (highest priority first): identity ->
standing constraints -> retrieved knowledge -> conversation history ->
resumable state -> current task. Assembly enforces the profile budget;
overflow aborts explicitly (compact-and-retry lands with the compaction
test plan; until then the compact step is an explicit not-implemented).

Implements: REQ-SI-FR-020 (ADR-001)
"""

from __future__ import annotations

from stockinsider.agent.profiles import Profile, envelope_for


class ContextBudgetError(RuntimeError):
    """Explicit budget-exceeded abort (blueprint §8.3).

    Implements: REQ-SI-FR-020 (ADR-001)
    """


class ContextLayerError(RuntimeError):
    """Explicit rejection of unknown layer names.

    Implements: REQ-SI-FR-020 (ADR-001)
    """


#: Priority order, blueprint §8.1.
CONTEXT_LAYERS: tuple[str, ...] = (
    "identity",
    "standing-constraints",
    "retrieved-knowledge",
    "conversation-history",
    "resumable-state",
    "current-task",
)


def estimate_tokens(text: str) -> int:
    """Deterministic conservative token estimate (4 chars per token).

    Implements: REQ-SI-FR-020 (ADR-001)
    """
    return max(1, (len(text) + 3) // 4)


class ContextAssembler:
    """Assembles layer parts under a profile budget (skeleton).

    Implements: REQ-SI-FR-020 (ADR-001)
    """

    def __init__(self, profile: Profile | str) -> None:
        """Bind the assembler to a profile's budget envelope."""
        self._envelope = envelope_for(profile)

    @property
    def max_session_tokens(self) -> int:
        """The profile's token ceiling (bound inclusive).

        Implements: REQ-SI-FR-020 (ADR-001)
        """
        return self._envelope.max_session_tokens

    def assemble(self, parts: dict[str, str]) -> str:
        """Concatenate known layers in priority order; abort on overflow.

        Implements: REQ-SI-FR-020 (ADR-001)
        """
        unknown = sorted(set(parts) - set(CONTEXT_LAYERS))
        if unknown:
            raise ContextLayerError(f"unknown context layer(s): {unknown}; expected subset of {list(CONTEXT_LAYERS)}")
        ordered = [parts[layer] for layer in CONTEXT_LAYERS if layer in parts]
        total = sum(estimate_tokens(part) for part in ordered)
        if total > self._envelope.max_session_tokens:
            raise ContextBudgetError(
                f"context budget exceeded: ~{total} tokens > {self._envelope.max_session_tokens} "
                f"(profile {self._envelope.profile.value}); compaction is not implemented yet - "
                "explicit abort per blueprint §8.3"
            )
        return "\n\n".join(ordered)

    def used_tokens(self, parts: dict[str, str]) -> int:
        """Estimated token total for a parts mapping (no assembly).

        Implements: REQ-SI-FR-020 (ADR-001)
        """
        return sum(estimate_tokens(part) for part in parts.values())
