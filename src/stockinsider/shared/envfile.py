"""Local untracked env-file (dotenv) reading, shared by agent and data.

Semantics (identical to the provider-key path): a real environment
variable always wins over the file; the file path resolves as
explicit argument, then the STOCKINSIDER_ENV_FILE override, then the
working-directory default. Values are trimmed; surrounding quotes are
stripped; blank lines and #-comments are ignored.

Implements: REQ-SI-SEC-001 (ADR-004)
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE_OVERRIDE = "STOCKINSIDER_ENV_FILE"
DEFAULT_FILE_NAME = ".env"


def env_file_path(explicit: Path | str | None = None) -> Path:
    """Resolve the env-file path: explicit, then override, then default.

    Implements: REQ-SI-SEC-001 (ADR-004)
    """
    if explicit is not None:
        return Path(explicit)
    return Path(os.environ.get(ENV_FILE_OVERRIDE, DEFAULT_FILE_NAME))


def read_env_file(explicit: Path | str | None = None) -> dict[str, str]:
    """Parse the env file into a dict; missing file yields {}.

    Implements: REQ-SI-SEC-001 (ADR-004)
    """
    path = env_file_path(explicit)
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        cleaned = value.strip().strip('"').strip("'")
        if cleaned:
            values[name.strip()] = cleaned
    return values


def env_value(name: str, explicit: Path | str | None = None) -> str | None:
    """Resolve one setting: a real environment variable wins, then the file.

    Implements: REQ-SI-SEC-001 (ADR-004)
    """
    from_env = os.environ.get(name)
    if from_env:
        return from_env
    return read_env_file(explicit).get(name)
