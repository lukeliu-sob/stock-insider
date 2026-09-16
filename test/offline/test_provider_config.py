"""Offline tests for provider configuration (TP-003, FR-021/SEC-001).

Covers: layered resolution (defaults < config.json < env), validation
rejections, atomic persistence, .env key handling (dotenv semantics,
masking, refusal to store secrets in config.json), the `config`
subcommand surface, and the mockable provider client.
"""

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from stockinsider.agent.profiles import PROFILE_BUDGETS, Profile
from stockinsider.agent.providers import (
    API_KEY_ENV,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderError,
    load_config,
    mask_key,
    resolve_api_key,
    resolve_config,
    save_config,
    write_env_api_key,
)
from stockinsider.cli.app import app

runner = CliRunner()


@pytest.fixture()
def env_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKINSIDER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("STOCKINSIDER_ENV_FILE", str(tmp_path / "data" / ".env"))
    monkeypatch.delenv("PROVIDER_BASE_URL", raising=False)
    monkeypatch.delenv("PROVIDER_CHAT_MODEL", raising=False)
    monkeypatch.delenv("PROVIDER_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    return tmp_path / "data"


# -- resolution layers ------------------------------------------------------


def test_defaults_when_unconfigured(env_root) -> None:
    resolved = resolve_config(env_root)
    assert resolved.chat_model == "deepseek-v4.1-flash"
    assert resolved.embedding_model == "deepseek-v4.1-flash"
    assert resolved.chat_base_url is None
    assert resolved.embedding_base_url is None
    assert resolved.budgets == {p.value: PROFILE_BUDGETS[p] for p in Profile}


def test_config_file_overrides_defaults(env_root) -> None:
    save_config({"chat_base_url": "https://api.example.com/v1", "chat_model": "m1"}, env_root)
    resolved = resolve_config(env_root)
    assert resolved.chat_base_url == "https://api.example.com/v1"
    assert resolved.chat_model == "m1"


def test_env_overrides_config_file(env_root, monkeypatch) -> None:
    save_config({"chat_base_url": "https://file.example.com/v1"}, env_root)
    monkeypatch.setenv("PROVIDER_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("PROVIDER_CHAT_MODEL", "env-model")
    resolved = resolve_config(env_root)
    assert resolved.chat_base_url == "https://env.example.com/v1"
    assert resolved.chat_model == "env-model"


def test_budget_overrides_roundtrip(env_root) -> None:
    save_config({"budget_quick": 12345}, env_root)
    resolved = resolve_config(env_root)
    assert resolved.budgets["quick"] == 12345
    assert resolved.budgets["standard"] == 100_000


# -- validation (explicit rejection) ----------------------------------------


def test_unknown_top_key_rejected(env_root) -> None:
    (env_root).mkdir(parents=True, exist_ok=True)
    (env_root / "config.json").write_text('{"config_version": 1, "mystery": 1}', encoding="utf-8")
    with pytest.raises(ProviderError, match="unknown config key"):
        load_config(env_root)


def test_bad_budget_value_rejected(env_root) -> None:
    (env_root).mkdir(parents=True, exist_ok=True)
    (env_root / "config.json").write_text('{"config_version": 1, "budgets": {"quick": "lots"}}', encoding="utf-8")
    with pytest.raises(ProviderError, match="positive integer"):
        load_config(env_root)


def test_broken_json_rejected(env_root) -> None:
    (env_root).mkdir(parents=True, exist_ok=True)
    (env_root / "config.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ProviderError, match="unreadable"):
        load_config(env_root)


def test_secret_keys_refused_in_config(env_root) -> None:
    with pytest.raises(ProviderError, match="never config.json"):
        save_config({"api_key": "sk-supersecret"}, env_root)


# -- API key resolution (.env, dotenv semantics) -----------------------------


def test_env_var_beats_env_file(env_root, monkeypatch) -> None:
    write_env_api_key("sk-fromfile123456", env_root / ".env")
    monkeypatch.setenv(API_KEY_ENV, "sk-fromenv1234567")
    key, source = resolve_api_key(env_root / ".env")
    assert key == "sk-fromenv1234567" and source == "environment"


def test_env_file_used_when_no_env_var(env_root) -> None:
    write_env_api_key("sk-filekey12345678", env_root / ".env")
    key, source = resolve_api_key(env_root / ".env")
    assert key == "sk-filekey12345678" and source == ".env"


def test_env_file_preserves_other_lines(env_root) -> None:
    path = env_root / ".env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# comment\nOTHER_VAR=1\n", encoding="utf-8")
    write_env_api_key("sk-firstkey1234567", path)
    write_env_api_key("sk-secondkey1234567", path)
    text = path.read_text(encoding="utf-8")
    assert "OTHER_VAR=1" in text and "# comment" in text
    assert "sk-firstkey" not in text
    key, _source = resolve_api_key(path)
    assert key == "sk-secondkey1234567"


def test_missing_key_is_none(env_root) -> None:
    key, source = resolve_api_key(env_root / ".env")
    assert key is None and source == "unset"


def test_mask_key() -> None:
    assert mask_key(None) == "unset"
    assert mask_key("short") == "set(****)"
    masked = mask_key("sk-abcdefghij123456")
    assert "abcdefghij" not in masked and masked.startswith("sk-") and masked.endswith("3456")


# -- provider client (mocked factory; no network) ----------------------------


class _FakeCompletion:
    def __init__(self, text: str) -> None:
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=text))]
        self.usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7)


class _FakeChatModule:
    def __init__(self, text: str) -> None:
        self.completions = SimpleNamespace(create=lambda **_kwargs: _FakeCompletion(text))


class _FakeClient:
    def __init__(self, text: str, base_url: str, api_key: str | None) -> None:
        self.chat = _FakeChatModule(text)
        self.base_url = base_url
        self.api_key = api_key


def test_provider_chat_returns_text_and_usage() -> None:
    config = ProviderConfig(
        chat_base_url="https://x.example/v1",
        chat_model="m",
        embedding_base_url=None,
        embedding_model="m",
        budgets={},
    )
    seen: dict[str, object] = {}

    def factory(base_url: str, api_key: str | None) -> _FakeClient:
        seen["base_url"] = base_url
        seen["api_key"] = api_key
        return _FakeClient("hello there", base_url, api_key)

    provider = OpenAICompatibleProvider(config, api_key="sk-t3st", client_factory=factory)
    text, usage = provider.chat([{"role": "user", "content": "hi"}])
    assert text == "hello there"
    assert usage == {"prompt_tokens": 11, "completion_tokens": 7}
    assert seen["base_url"] == "https://x.example/v1"


def test_provider_refuses_unconfigured_endpoint() -> None:
    config = ProviderConfig(
        chat_base_url=None,
        chat_model="m",
        embedding_base_url=None,
        embedding_model="m",
        budgets={},
    )
    provider = OpenAICompatibleProvider(config, api_key="k")
    with pytest.raises(ProviderError, match="refusing to guess an endpoint"):
        provider.chat([{"role": "user", "content": "hi"}])


def test_provider_refuses_missing_key() -> None:
    config = ProviderConfig(
        chat_base_url="https://x.example/v1",
        chat_model="m",
        embedding_base_url=None,
        embedding_model="m",
        budgets={},
    )
    provider = OpenAICompatibleProvider(config, api_key=None)
    with pytest.raises(ProviderError, match=API_KEY_ENV):
        provider.chat([{"role": "user", "content": "hi"}])


# -- CLI `config` surface ----------------------------------------------------


def test_config_show_masks_key(env_root, monkeypatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, "sk-livekeyabcdefgh")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "sk-livekeyabcdefgh" not in result.output
    assert "sk-...efgh" in result.output
    assert "deepseek-v4.1-flash" in result.output
    assert "UNCONFIGURED" in result.output


def test_config_set_persists_non_secret_values(env_root) -> None:
    result = runner.invoke(
        app,
        ["config", "set", "--chat-base-url", "https://api.example.com/v1", "--budget-quick", "5000"],
    )
    assert result.exit_code == 0
    raw = load_config(env_root)
    assert raw["providers"]["chat"]["base_url"] == "https://api.example.com/v1"
    assert raw["budgets"]["quick"] == 5000
    assert "api_key" not in raw.get("providers", {}).get("chat", {})


def test_config_set_api_key_goes_to_env_file_not_config(env_root) -> None:
    result = runner.invoke(app, ["config", "set", "--api-key", "sk-cliwritten12345"])
    assert result.exit_code == 0
    assert "sk-cliwritten12345" not in result.output  # masked in output
    key, source = resolve_api_key(env_root / ".env")
    assert key == "sk-cliwritten12345" and source == ".env"
    assert not (env_root / "config.json").exists() or "sk-cliwritten" not in (env_root / "config.json").read_text(
        encoding="utf-8"
    )


def test_config_set_with_nothing_is_explicit_error(env_root) -> None:
    result = runner.invoke(app, ["config", "set"])
    assert result.exit_code != 0
    assert "nothing to set" in result.output


def test_config_path_command(env_root) -> None:
    result = runner.invoke(app, ["config", "path"])
    assert result.exit_code == 0
    assert "config.json" in result.output
