"""Analysis profiles and context budget envelopes (blueprint §7.5, §8.3).

Profiles are chosen at session start and fixed for the session lifetime
(FR-020); the budget envelope governs context assembly and aborts
explicitly on overflow. Budget ceilings are user-configurable via
data/config.json (COST-001); the single writer for overrides is the
config resolution path (agent.providers), applied at session start.

Implements: REQ-SI-FR-020, REQ-SI-COST-001 (ADR-001)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Profile(str, Enum):
    """Analysis profile: governs context budget and retrieval windows.

    Implements: REQ-SI-FR-020 (ADR-001)
    """

    quick = "quick"
    standard = "standard"
    deep = "deep"


@dataclass(frozen=True)
class BudgetEnvelope:
    """Per-session token ceiling for a profile (inclusive at the bound).

    Implements: REQ-SI-FR-020 (ADR-001)
    """

    profile: Profile
    max_session_tokens: int


#: Default budget ceilings (blueprint §8.3, COST-001); config.json overrides.
PROFILE_BUDGETS: dict[Profile, int] = {
    Profile.quick: 30_000,
    Profile.standard: 100_000,
    Profile.deep: 400_000,
}


def apply_budget_overrides(budgets: dict[str, int]) -> None:
    """Apply user-configured budget ceilings (single writer: config resolution).

    Implements: REQ-SI-COST-001 (ADR-001)
    """
    for name, value in budgets.items():
        PROFILE_BUDGETS[Profile(name)] = int(value)


def envelope_for(profile: Profile | str) -> BudgetEnvelope:
    """Return the token budget envelope for a profile.

    Implements: REQ-SI-FR-020 (ADR-001)
    """
    prof = Profile(profile)
    return BudgetEnvelope(profile=prof, max_session_tokens=PROFILE_BUDGETS[prof])


def within_budget(profile: Profile | str, used_tokens: int) -> bool:
    """True if a token count fits the profile envelope (bound inclusive).

    Implements: REQ-SI-FR-020 (ADR-001)
    """
    envelope = envelope_for(profile)
    return used_tokens <= envelope.max_session_tokens
