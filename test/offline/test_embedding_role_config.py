"""Offline tests for the embedding-role configuration (TP-036, SEC-001/FR-021).

The embedding role is configured as one unit in the env file:
EMBEDDING_API_KEY, EMBEDDING_BASE_URL, EMBEDDING_MODEL. The chat key
serves the embedding role only on the chat endpoint's host, so it is
never sent to a different vendor.

Implements: REQ-SI-SEC-001, REQ-SI-FR-021 (ADR-001)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from stockinsider.agent.providers import (
    API_KEY_ENV,
    EMBEDDING_API_KEY_ENV,
    EMBEDDING_BASE_URL_ENV,
    EMBEDDING_MODEL_ENV,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderError,
    resolve_api_key,
    resolve_config,
    resolve_embedding_api_key,
    save_config,
    write_env_api_key,
)
from stockinsider.cli.app import app

runner = CliRunner()

CHAT_URL = "https://api.deepseek.com/v1"
EMBED_URL = "https://maas.qianwenaiapi.com/compatible-mode/v1"


@pytest.fixture()
def env_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKINSIDER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(tmp_path / "data" / ".env"))
    for name in (
        "PROVIDER_BASE_URL",
        "PROVIDER_CHAT_MODEL",
        "PROVIDER_EMBEDDING_MODEL",
        API_KEY_ENV,
        EMBEDDING_API_KEY_ENV,
        EMBEDDING_BASE_URL_ENV,
        EMBEDDING_MODEL_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "data").mkdir()
    return tmp_path / "data"


def _write_env(env_root, **values: str) -> None:
    lines = [f"{name}={value}" for name, value in values.items()]
    (env_root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _config(chat_url: str | None = CHAT_URL, embed_url: str | None = EMBED_URL) -> ProviderConfig:
    return ProviderConfig(
        chat_base_url=chat_url,
        chat_model="chat-model",
        embedding_base_url=embed_url,
        embedding_model="embed-model",
    )


# -- endpoint and model from the env file -----------------------------------


def test_env_file_configures_embedding_role(env_root) -> None:
    _write_env(env_root, EMBEDDING_BASE_URL=EMBED_URL, EMBEDDING_MODEL="qwen3.7-text-embedding-flash")
    resolved = resolve_config(env_root)
    assert resolved.embedding_base_url == EMBED_URL
    assert resolved.embedding_model == "qwen3.7-text-embedding-flash"
    # the chat role is untouched by embedding settings
    assert resolved.chat_base_url is None
    assert resolved.chat_model == "deepseek-flash"


def test_role_specific_values_win_over_generic_and_config(env_root, monkeypatch) -> None:
    save_config({"embedding_base_url": "https://config.example.com/v1", "embedding_model": "cfg-model"}, env_root)
    monkeypatch.setenv("PROVIDER_BASE_URL", CHAT_URL)
    monkeypatch.setenv("PROVIDER_EMBEDDING_MODEL", "generic-model")
    _write_env(env_root, EMBEDDING_BASE_URL=EMBED_URL, EMBEDDING_MODEL="qwen3.7-text-embedding-flash")
    resolved = resolve_config(env_root)
    assert resolved.embedding_base_url == EMBED_URL
    assert resolved.embedding_model == "qwen3.7-text-embedding-flash"
    assert resolved.chat_base_url == CHAT_URL


def test_real_environment_wins_over_env_file(env_root, monkeypatch) -> None:
    _write_env(env_root, EMBEDDING_MODEL="file-model")
    monkeypatch.setenv(EMBEDDING_MODEL_ENV, "env-model")
    assert resolve_config(env_root).embedding_model == "env-model"


def test_without_embedding_settings_layers_are_unchanged(env_root) -> None:
    save_config({"embedding_base_url": "https://config.example.com/v1"}, env_root)
    resolved = resolve_config(env_root)
    assert resolved.embedding_base_url == "https://config.example.com/v1"
    assert resolved.embedding_model == "deepseek-flash"


# -- the embedding key ------------------------------------------------------


def test_embedding_key_from_env_file(env_root) -> None:
    _write_env(env_root, EMBEDDING_API_KEY="sk-embedfile12")
    key, source = resolve_embedding_api_key(_config(), env_root / ".env")
    assert key == "sk-embedfile12"
    assert source == ".env"


def test_embedding_key_environment_wins(env_root, monkeypatch) -> None:
    _write_env(env_root, EMBEDDING_API_KEY="sk-embedfile12")
    monkeypatch.setenv(EMBEDDING_API_KEY_ENV, "sk-embedenv123")
    key, source = resolve_embedding_api_key(_config(), env_root / ".env")
    assert key == "sk-embedenv123"
    assert source == "environment"


def test_other_host_without_embedding_key_is_unset(env_root) -> None:
    _write_env(env_root, PROVIDER_API_KEY="sk-chatvendor1")
    key, source = resolve_embedding_api_key(_config(), env_root / ".env")
    assert key is None
    assert source == "unset"


def test_same_host_falls_back_to_chat_key(env_root) -> None:
    _write_env(env_root, PROVIDER_API_KEY="sk-chatvendor1")
    key, source = resolve_embedding_api_key(_config(embed_url=CHAT_URL), env_root / ".env")
    assert key == "sk-chatvendor1"
    assert "same host" in source


def test_chat_key_is_never_sent_to_another_vendor(env_root, monkeypatch) -> None:
    # adversarial: the chat key is present and the embedding host differs;
    # nothing may reach the embedding endpoint carrying the chat key
    monkeypatch.setenv(API_KEY_ENV, "sk-chatvendor1")
    monkeypatch.setenv("EGRESS_EXTRA_HOSTS", "maas.qianwenaiapi.com")
    built: list[dict[str, object]] = []

    def factory(**kwargs):
        built.append(kwargs)
        raise AssertionError("no client may be built")

    config = _config()
    key, _source = resolve_embedding_api_key(config)
    provider = OpenAICompatibleProvider(config, api_key=key, client_factory=factory)
    with pytest.raises(ProviderError, match=EMBEDDING_API_KEY_ENV):
        provider.embed(["headline"])
    assert built == []


def test_embedding_call_uses_the_embedding_key(env_root, monkeypatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, "sk-chatvendor1")
    monkeypatch.setenv(EMBEDDING_API_KEY_ENV, "sk-embedvend12")
    monkeypatch.setenv("EGRESS_EXTRA_HOSTS", "maas.qianwenaiapi.com")
    seen: list[dict[str, object]] = []

    def factory(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(
            embeddings=SimpleNamespace(
                create=lambda **_: SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])
            )
        )

    config = _config()
    key, _source = resolve_embedding_api_key(config)
    provider = OpenAICompatibleProvider(config, api_key=key, client_factory=factory)
    assert provider.embed(["headline"]) == [[0.1, 0.2]]
    assert seen == [{"base_url": EMBED_URL, "api_key": "sk-embedvend12"}]


def test_unknown_key_variable_refused(env_root) -> None:
    with pytest.raises(ProviderError, match="unknown key variable"):
        resolve_api_key(name="OTHER_SECRET")
    with pytest.raises(ProviderError, match="unknown key variable"):
        write_env_api_key("sk-x1234567890", env_root / ".env", name="OTHER_SECRET")


# -- egress extension from the env file (ADR-004 Am2) ------------------------


def test_egress_extra_hosts_read_from_env_file(env_root, monkeypatch) -> None:
    from stockinsider.shared.egress import extra_hosts_from_env, validate_egress_url

    monkeypatch.delenv("EGRESS_EXTRA_HOSTS", raising=False)
    _write_env(env_root, EGRESS_EXTRA_HOSTS="maas.qianwenaiapi.com")
    assert extra_hosts_from_env() == ("maas.qianwenaiapi.com",)
    validate_egress_url(EMBED_URL, extra_allowed=extra_hosts_from_env())


def test_egress_unlisted_host_still_rejected(env_root, monkeypatch) -> None:
    from stockinsider.shared.egress import EgressViolationError, extra_hosts_from_env, validate_egress_url

    monkeypatch.delenv("EGRESS_EXTRA_HOSTS", raising=False)
    _write_env(env_root, EGRESS_EXTRA_HOSTS="maas.qianwenaiapi.com")
    with pytest.raises(EgressViolationError):
        validate_egress_url("https://evil.example.com/v1", extra_allowed=extra_hosts_from_env())


# -- CLI surface -------------------------------------------------------------


def test_cli_writes_embedding_key_to_env_only(env_root) -> None:
    result = runner.invoke(app, ["config", "set", "--embedding-api-key", "sk-embedcli123"])
    assert result.exit_code == 0, result.output
    assert "sk-embedcli123" not in result.output
    env_text = (env_root / ".env").read_text(encoding="utf-8")
    assert "EMBEDDING_API_KEY=sk-embedcli123" in env_text
    assert not (env_root / "config.json").exists()


def test_cli_show_masks_embedding_key(env_root) -> None:
    _write_env(
        env_root,
        EMBEDDING_API_KEY="sk-embedshow12",
        EMBEDDING_BASE_URL=EMBED_URL,
        EMBEDDING_MODEL="qwen3.7-text-embedding-flash",
    )
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "sk-embedshow12" not in result.output
    assert "embed key:" in result.output
    assert "qwen3.7-text-embedding-flash @ " + EMBED_URL in result.output


def test_config_json_refuses_embedding_key(env_root) -> None:
    with pytest.raises(ProviderError, match="secret material refused"):
        save_config({"embedding_api_key": "sk-x1234567890"}, env_root)
