"""Provenance stamp types (GOV-005): the authoritative field set.

Every session record carries model identifier, prompt version, and
provider configuration; turns inherit their session's stamp. Explicit
placeholders (PLACEHOLDER_PREFIX) mark not-yet-resolved values — never
blank, never fabricated.

Implements: REQ-SI-GOV-005 (ADR-004)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

PROVENANCE_FIELDS: tuple[str, ...] = ("model_id", "prompt_version", "provider_config")
PLACEHOLDER_PREFIX = "unset-until"


class ProvenanceError(RuntimeError):
    """Explicit provenance validation failure (GOV-005).

    Implements: REQ-SI-GOV-005 (ADR-004)
    """


@dataclass(frozen=True)
class ProvenanceStamp:
    """Model/prompt/provider stamp carried by every session record.

    Implements: REQ-SI-GOV-005 (ADR-004)
    """

    model_id: str
    prompt_version: str
    provider_config: str

    def to_record(self) -> dict[str, str]:
        """Render as the session-record mapping.

        Implements: REQ-SI-GOV-005 (ADR-004)
        """
        return dict(asdict(self))

    @classmethod
    def from_record(cls, record: dict[str, str]) -> ProvenanceStamp:
        """Build from a session-record mapping; validates first.

        Implements: REQ-SI-GOV-005 (ADR-004)
        """
        validate_provenance(record)
        return cls(**{field: record[field] for field in PROVENANCE_FIELDS})


def validate_provenance(record: dict[str, str]) -> None:
    """Reject missing fields, blank values, and wrong types (GOV-005 fit).

    Implements: REQ-SI-GOV-005 (ADR-004)
    """
    missing = [field for field in PROVENANCE_FIELDS if field not in record]
    if missing:
        raise ProvenanceError(f"provenance missing field(s): {missing} (GOV-005: zero missing fields)")
    for field in PROVENANCE_FIELDS:
        value = record[field]
        if not isinstance(value, str) or not value.strip():
            raise ProvenanceError(f"provenance field {field!r} must be a non-empty string (GOV-005)")
