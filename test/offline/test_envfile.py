"""Offline tests for shared env-file reading and resolver wiring (BD-009 fix).

Covers: dotenv parsing (comments, quotes, blank lines), real-env-wins
semantics, and the resolver wiring fix — a key present in env OR the
env file wires the stdlib live transport; absence raises the explicit
unavailable error (INV-003).

Implements: REQ-SI-SEC-001, REQ-SI-FR-004, REQ-SI-INV-003 (ADR-004, ADR-002)
"""

import pytest

from stockinsider.data.store.resolver import ResolverUnavailable, SymbolResolver, stdlib_transport
from stockinsider.shared.envfile import env_value, read_env_file


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Point the env-file lookup at a tmp file; clear real keys."""
    env_file = tmp_path / "keys.env"
    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(env_file))
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    return env_file


def test_read_env_file_parses_quotes_and_comments(_isolate_env) -> None:
    _isolate_env.write_text(
        "# comment\n\nEODHD_API_KEY=\"abc123\"\nOTHER_KEY='x y'\nEMPTY=\nBROKEN LINE\n",
        encoding="utf-8",
    )
    values = read_env_file()
    assert values == {"EODHD_API_KEY": "abc123", "OTHER_KEY": "x y"}


def test_real_environment_wins_over_file(_isolate_env, monkeypatch) -> None:
    _isolate_env.write_text("EODHD_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("EODHD_API_KEY", "from-env")
    assert env_value("EODHD_API_KEY") == "from-env"


def test_missing_file_is_empty(_isolate_env) -> None:
    assert read_env_file() == {}


def test_resolver_wires_live_transport_from_file_key(_isolate_env) -> None:
    _isolate_env.write_text("EODHD_API_KEY=file-key\n", encoding="utf-8")
    resolver = SymbolResolver()
    assert resolver.is_live()
    assert resolver._transport is stdlib_transport  # noqa: SLF001 — wiring seam


def test_resolver_explicit_injection_still_wins(_isolate_env) -> None:
    _isolate_env.write_text("EODHD_API_KEY=file-key\n", encoding="utf-8")
    captured: dict[str, str] = {}

    def fake_transport(url: str, params: dict[str, str]) -> str:
        captured.update(params)
        return "[]"

    resolver = SymbolResolver(transport=fake_transport, api_key="explicit")
    assert resolver.search("zzz-nothing") == []
    assert captured["api_token"] == "explicit"


def test_resolver_without_key_is_explicit_unavailable(_isolate_env) -> None:
    resolver = SymbolResolver()
    assert not resolver.is_live()
    with pytest.raises(ResolverUnavailable, match="EODHD_API_KEY"):
        resolver.search("Tencent")
