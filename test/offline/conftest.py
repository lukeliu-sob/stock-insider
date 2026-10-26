"""Offline-suite isolation from the developer's real env file (TP-036).

Provider endpoints, models and keys resolve from the environment and
then the env file. Offline tests must never see a real .env (it may
carry live endpoints and keys), so every test starts with the env
file pointed at a path that does not exist. Tests that need an env
file set STOCKINSIDER_ENV_FILE themselves, which overrides this.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_env_file(tmp_path_factory, monkeypatch):
    missing = tmp_path_factory.mktemp("no-env") / ".env"
    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(missing))
