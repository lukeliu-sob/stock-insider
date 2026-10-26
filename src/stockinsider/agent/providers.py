"""Provider configuration and OpenAI-compatible Chat Completions access.

Wire surface: chat completions + embeddings, stateless calls only —
context is reconstructed locally per session (INV-001 alignment).
Configuration is layered: code defaults < data/config.json (no secret
material) < environment overrides (for CI and headless use). The API
key resolves from the PROVIDER_API_KEY environment variable or the
repo-root .env file (dotenv semantics: a real environment variable
always wins); it is never stored in config.json. The embedding role
is configured as one unit in the same env file (TP-036):
EMBEDDING_API_KEY, EMBEDDING_BASE_URL and EMBEDDING_MODEL, so a chat
vendor's key is never sent to a different embedding vendor.

Implements: REQ-SI-FR-021, REQ-SI-SEC-001 (ADR-001)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from stockinsider.agent.profiles import PROFILE_BUDGETS, Profile
from stockinsider.shared.envfile import env_file_path as shared_env_file_path
from stockinsider.shared.envfile import env_value, read_env_file

DEFAULT_CHAT_MODEL = "deepseek-flash"
DEFAULT_EMBEDDING_MODEL = "deepseek-flash"
API_KEY_ENV = "PROVIDER_API_KEY"
#: Embedding-role key (TP-036): the embedding vendor may differ from
#: the chat vendor, and each vendor only ever sees its own key.
EMBEDDING_API_KEY_ENV = "EMBEDDING_API_KEY"
#: Embedding-role endpoint and model (TP-036), read from the
#: environment or the env file; they win over the generic
#: PROVIDER_BASE_URL / PROVIDER_EMBEDDING_MODEL and config.json.
EMBEDDING_BASE_URL_ENV = "EMBEDDING_BASE_URL"
EMBEDDING_MODEL_ENV = "EMBEDDING_MODEL"
_KEY_ENV_NAMES = (API_KEY_ENV, EMBEDDING_API_KEY_ENV)
CONFIG_VERSION = 1

_TOP_KEYS = {"config_version", "providers", "budgets"}
_ROLE_KEYS = {"base_url", "model"}


class ProviderError(RuntimeError):
    """Explicit provider-layer failure: never silent, never fabricated.

    Implements: REQ-SI-FR-021 (ADR-001)
    """


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved, layered provider and budget configuration.

    Implements: REQ-SI-FR-021, REQ-SI-COST-001 (ADR-001)
    """

    chat_base_url: str | None
    chat_model: str
    embedding_base_url: str | None
    embedding_model: str
    budgets: dict[str, int] = field(default_factory=dict)


def data_root(root: Path | str | None = None) -> Path:
    """Resolve the data root: explicit, then env override, then ./data.

    Implements: REQ-SI-FR-021 (ADR-001)
    """
    if root is not None:
        return Path(root)
    return Path(os.environ.get("STOCKINSIDER_DATA_ROOT", "data"))


def config_path(root: Path | str | None = None) -> Path:
    """Path of the non-secret configuration file.

    Implements: REQ-SI-FR-021 (ADR-001)
    """
    return data_root(root) / "config.json"


def _validate(raw: dict[str, Any]) -> None:
    """Reject unknown keys, bad types, and version mismatches explicitly.

    Implements: REQ-SI-FR-021 (ADR-001)
    """
    unknown = sorted(set(raw) - _TOP_KEYS)
    if unknown:
        raise ProviderError(f"unknown config key(s): {unknown}; allowed: {sorted(_TOP_KEYS)}")
    version = raw.get("config_version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        raise ProviderError(f"unsupported config_version {version!r}; expected {CONFIG_VERSION}")
    providers = raw.get("providers", {})
    if not isinstance(providers, dict):
        raise ProviderError("config 'providers' must be a mapping")
    for role in ("chat", "embedding"):
        section = providers.get(role, {})
        if not isinstance(section, dict):
            raise ProviderError(f"config providers.{role} must be a mapping")
        bad = sorted(set(section) - _ROLE_KEYS)
        if bad:
            raise ProviderError(f"unknown key(s) in providers.{role}: {bad}; allowed: {sorted(_ROLE_KEYS)}")
        for key in ("base_url", "model"):
            if key in section and not isinstance(section[key], str):
                raise ProviderError(f"providers.{role}.{key} must be a string")
    budgets = raw.get("budgets", {})
    if not isinstance(budgets, dict):
        raise ProviderError("config 'budgets' must be a mapping")
    valid_profiles = {p.value for p in Profile}
    for name, value in budgets.items():
        if name not in valid_profiles:
            raise ProviderError(f"unknown budget profile {name!r}; allowed: {sorted(valid_profiles)}")
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ProviderError(f"budget for {name!r} must be a positive integer")


def load_config(root: Path | str | None = None) -> dict[str, Any]:
    """Load and validate config.json; {} when the file is absent.

    Implements: REQ-SI-FR-021 (ADR-001)
    """
    path = config_path(root)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ProviderError(f"config file unreadable ({path}): {exc}") from exc
    if not isinstance(raw, dict):
        raise ProviderError(f"config file must contain a JSON object ({path})")
    _validate(raw)
    return raw


def save_config(
    updates: dict[str, Any],
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Read-modify-validate-write config.json atomically; returns the new raw.

    Implements: REQ-SI-FR-021 (ADR-001)
    """
    merged_updates: dict[str, Any] = json.loads(json.dumps(updates))  # deep copy
    for flat in merged_updates:
        if any(token in flat.lower() for token in ("api_key", "key", "secret")):
            raise ProviderError(
                f"secret material refused in config key {flat!r}: keys belong in {API_KEY_ENV} / "
                f"{EMBEDDING_API_KEY_ENV} / .env, never config.json (SEC-001)"
            )
    current = load_config(root)
    providers = {**current.get("providers", {})}
    budgets = {**current.get("budgets", {})}
    for flat_key, value in merged_updates.items():
        if "_" not in flat_key:
            raise ProviderError(f"unknown config set key: {flat_key!r}")
        role, _, key = flat_key.partition("_")
        if role in ("chat", "embedding") and key in _ROLE_KEYS:
            section_ref = providers.setdefault(role, {})
            section_ref[key] = value
        elif role == "budget" and key in {p.value for p in Profile}:
            budgets[key] = value
        else:
            raise ProviderError(f"unknown config set key: {flat_key!r}")
    new_raw = {
        "config_version": CONFIG_VERSION,
        "providers": providers,
        **({"budgets": budgets} if budgets else {}),
    }
    _validate(new_raw)
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new_raw, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return new_raw


def resolve_config(root: Path | str | None = None) -> ProviderConfig:
    """Layered resolution: code defaults < config.json < environment.

    Every override reads the real environment first, then the env file
    (TP-036), so the whole provider setup can live in .env:
    PROVIDER_BASE_URL / PROVIDER_CHAT_MODEL / PROVIDER_EMBEDDING_MODEL
    and the embedding role's EMBEDDING_BASE_URL / EMBEDDING_MODEL. The
    role-specific values win over the generic ones, so one shared
    PROVIDER_BASE_URL never redirects the embedding role to the chat
    vendor.

    Implements: REQ-SI-FR-021 (ADR-001)
    """
    raw = load_config(root)
    providers = raw.get("providers", {})
    chat = providers.get("chat", {})
    embedding = providers.get("embedding", {})
    env_base = env_value("PROVIDER_BASE_URL")
    env_chat_model = env_value("PROVIDER_CHAT_MODEL")
    env_embedding_model = env_value("PROVIDER_EMBEDDING_MODEL")
    budgets = {profile.value: int(value) for profile, value in dict(PROFILE_BUDGETS).items()}
    budgets.update({k: int(v) for k, v in raw.get("budgets", {}).items()})
    return ProviderConfig(
        chat_base_url=env_base or chat.get("base_url"),
        chat_model=env_chat_model or chat.get("model") or DEFAULT_CHAT_MODEL,
        embedding_base_url=env_value(EMBEDDING_BASE_URL_ENV) or env_base or embedding.get("base_url"),
        embedding_model=(
            env_value(EMBEDDING_MODEL_ENV)
            or env_embedding_model
            or embedding.get("model")
            or DEFAULT_EMBEDDING_MODEL
        ),
        budgets=budgets,
    )


def env_file_path(explicit: Path | str | None = None) -> Path:
    """Resolve the env-file path (delegates to the shared reader; DE-07).

    Implements: REQ-SI-SEC-001 (ADR-004)
    """
    return shared_env_file_path(explicit)


def resolve_api_key(
    explicit_file: Path | str | None = None,
    *,
    name: str = API_KEY_ENV,
) -> tuple[str | None, str]:
    """Resolve the API key: environment wins, then the env file; (key, source).

    Parsing lives in shared/envfile (one dotenv parser for the whole
    codebase since DE-07); semantics unchanged and test-pinned. `name`
    selects the key variable (TP-036: the embedding role has its own).

    Implements: REQ-SI-SEC-001 (ADR-004)
    """
    if name not in _KEY_ENV_NAMES:
        raise ProviderError(f"unknown key variable {name!r}; allowed: {list(_KEY_ENV_NAMES)}")
    from_env = os.environ.get(name)
    if from_env:
        return from_env, "environment"
    from_file = read_env_file(explicit_file).get(name)
    if from_file:
        return from_file, ".env"
    return None, "unset"


def _host(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).hostname
    return host.lower().rstrip(".") if host else None


def resolve_embedding_api_key(
    config: ProviderConfig,
    explicit_file: Path | str | None = None,
) -> tuple[str | None, str]:
    """Resolve the embedding-role key; (key, source).

    EMBEDDING_API_KEY wins (environment, then the env file). Without
    it, PROVIDER_API_KEY is used only when the embedding endpoint is on
    the chat endpoint's host (one vendor); for any other host the
    result is unset, so the chat vendor's key is never sent to another
    vendor and the caller reports the missing key explicitly (INV-003).

    Implements: REQ-SI-SEC-001, REQ-SI-FR-021 (ADR-001)
    """
    key, source = resolve_api_key(explicit_file, name=EMBEDDING_API_KEY_ENV)
    if key:
        return key, source
    embedding_host = _host(config.embedding_base_url)
    if embedding_host is not None and embedding_host == _host(config.chat_base_url):
        chat_key, chat_source = resolve_api_key(explicit_file)
        if chat_key:
            return chat_key, f"{API_KEY_ENV} via {chat_source}, same host"
    return None, "unset"


def mask_key(key: str | None) -> str:
    """Mask a key for display: never render the full secret.

    Implements: REQ-SI-SEC-001 (ADR-001)
    """
    if not key:
        return "unset"
    if len(key) <= 8:
        return "set(****)"
    return f"{key[:3]}...{key[-4:]}"


def write_env_api_key(
    value: str,
    explicit_file: Path | str | None = None,
    *,
    name: str = API_KEY_ENV,
) -> Path:
    """Create or update a key variable in .env; other lines preserved.

    `name` is PROVIDER_API_KEY by default, or EMBEDDING_API_KEY.

    Implements: REQ-SI-SEC-001 (ADR-001)
    """
    if name not in _KEY_ENV_NAMES:
        raise ProviderError(f"unknown key variable {name!r}; allowed: {list(_KEY_ENV_NAMES)}")
    if not value.strip():
        raise ProviderError("refusing to write an empty API key")
    path = env_file_path(explicit_file)
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        line_name, _, _ = stripped.partition("=")
        if line_name.strip() == name:
            lines[index] = f"{name}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{name}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


@dataclass(frozen=True)
class ChatOutcome:
    """One provider completion: text and/or tool calls, with usage.

    Implements: REQ-SI-FR-021, REQ-SI-FR-019 (ADR-001)
    """

    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


class OpenAICompatibleProvider:
    """Thin stateless client over Chat Completions and embeddings.

    Explicit failures only: no retries with silent fallbacks, no
    default endpoints. The client factory is injectable so offline
    tests run without network.

    Implements: REQ-SI-FR-021 (ADR-001)
    """

    def __init__(
        self,
        config: ProviderConfig,
        api_key: str | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        """Bind configuration, key, and optional client factory."""
        self._config = config
        self._api_key = api_key
        self._client_factory = client_factory

    def _client(self, base_url: str) -> Any:
        # M9 (TP-017): the model runtime is the last hop out - every
        # provider URL passes the same egress whitelist as data fetching.
        # ADR-004 Am2 (TP-018): a policy rejection is an explicit
        # ProviderError, never a bare EgressViolationError escaping the
        # REPL's handler (the old path crashed the session into a stuck
        # "active" state on first question).
        from stockinsider.shared.egress import (
            EgressViolationError,
            provider_egress_allowed,
            validate_egress_url,
        )

        try:
            validate_egress_url(base_url, extra_allowed=provider_egress_allowed())
        except EgressViolationError as exc:
            raise ProviderError(f"egress whitelist rejected the model endpoint ({exc})") from exc
        if self._client_factory is not None:
            return self._client_factory(base_url=base_url, api_key=self._api_key)
        from openai import OpenAI

        return OpenAI(base_url=base_url, api_key=self._api_key)

    def chat(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
        """One chat-completions call; returns (text, usage).

        Implements: REQ-SI-FR-021 (ADR-001)
        """
        if not self._config.chat_base_url:
            raise ProviderError(
                "chat base_url is not configured; run `stockinsider config set --chat-base-url ...` "
                "or set PROVIDER_BASE_URL — refusing to guess an endpoint (INV-003)"
            )
        if not self._api_key:
            raise ProviderError(
                f"{API_KEY_ENV} is not set; provide it via the environment or "
                "`stockinsider config set --api-key` (writes .env)"
            )
        client = self._client(self._config.chat_base_url)
        try:
            response = client.chat.completions.create(
                model=self._config.chat_model,
                messages=messages,
            )
        except Exception as exc:  # provider errors are surfaced, never swallowed
            raise ProviderError(f"chat call failed: {exc}") from exc
        text = response.choices[0].message.content or ""
        usage = response.usage
        usage_dict = (
            {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
            }
            if usage
            else {}
        )
        return text, usage_dict

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        stream_sink: Callable[[str], None] | None = None,
    ) -> ChatOutcome:
        """One stateless completion with optional tool specs and streaming.

        stream_sink receives text deltas as produced (FR-019: the first
        delta reaches the caller strictly before completion returns);
        tools is the OpenAI function-tool list. Returns the aggregated
        ChatOutcome (text, parsed tool calls, usage).

        Implements: REQ-SI-FR-021, REQ-SI-FR-019 (ADR-001)
        """
        if not self._config.chat_base_url:
            raise ProviderError(
                "chat base_url is not configured; run `stockinsider config set --chat-base-url ...` "
                "or set PROVIDER_BASE_URL — refusing to guess an endpoint (INV-003)"
            )
        if not self._api_key:
            raise ProviderError(
                f"{API_KEY_ENV} is not set; provide it via the environment or "
                "`stockinsider config set --api-key` (writes the dotenv file)"
            )
        kwargs: dict[str, Any] = {
            "model": self._config.chat_model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        client = self._client(self._config.chat_base_url)
        if stream_sink is None:
            try:
                response = client.chat.completions.create(**kwargs)
            except Exception as exc:
                raise ProviderError(f"chat call failed: {exc}") from exc
            choice = response.choices[0]
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or ""},
                }
                for tc in (choice.message.tool_calls or [])
            ]
            response_usage = response.usage
            return ChatOutcome(
                text=choice.message.content or "",
                tool_calls=tool_calls,
                usage=(
                    {
                        "prompt_tokens": response_usage.prompt_tokens,
                        "completion_tokens": response_usage.completion_tokens,
                    }
                    if response_usage
                    else {}
                ),
            )
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        try:
            chunks = client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise ProviderError(f"chat call failed: {exc}") from exc
        text_parts: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, int] = {}
        try:
            for chunk in chunks:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    usage = {
                        "prompt_tokens": chunk_usage.prompt_tokens,
                        "completion_tokens": chunk_usage.completion_tokens,
                    }
                for choice in getattr(chunk, "choices", None) or []:
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue
                    piece = getattr(delta, "content", None)
                    if piece:
                        text_parts.append(piece)
                        stream_sink(piece)
                    for tc in getattr(delta, "tool_calls", None) or []:
                        index = tc.index
                        slot = calls.setdefault(
                            index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                        )
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function and tc.function.name:
                            slot["function"]["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            slot["function"]["arguments"] += tc.function.arguments
        except Exception as exc:  # H5: mid-stream breaks are provider errors
            raise ProviderError(f"chat stream failed mid-response: {exc}") from exc

        return ChatOutcome(
            text="".join(text_parts),
            tool_calls=[calls[i] for i in sorted(calls)],
            usage=usage,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """One embeddings call; returns one vector per input text.

        Implements: REQ-SI-FR-021 (ADR-001)
        """
        if not self._config.embedding_base_url:
            raise ProviderError(
                "embedding base_url is not configured; run `stockinsider config set --embedding-base-url ...` "
                "or set PROVIDER_BASE_URL — refusing to guess an endpoint (INV-003)"
            )
        if not self._api_key:
            raise ProviderError(
                f"{EMBEDDING_API_KEY_ENV} is not set (embedding call refused); {API_KEY_ENV} "
                "serves the embedding role only when it shares the chat endpoint's host"
            )
        client = self._client(self._config.embedding_base_url)
        try:
            response = client.embeddings.create(
                model=self._config.embedding_model,
                input=texts,
            )
        except Exception as exc:
            raise ProviderError(f"embedding call failed: {exc}") from exc
        return [item.embedding for item in response.data]
