from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .errors import ShelpError
from .models import ProviderSettings
from .utils import env_value

if TYPE_CHECKING:
    from .ui import TerminalUI


SUPPORTED_PROVIDERS = ("anthropic", "openai", "gemini")
MODEL_SUGGESTIONS = {
    "anthropic": ["claude-sonnet-4-6", "claude-haiku-4-5"],
    "openai": ["gpt-4.1-mini", "gpt-4.1"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro"],
}


def config_path() -> Path:
    override = env_value("SHELP_CONFIG_PATH", "AI_HELP_CONFIG_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "shelp" / "config.yaml"


def legacy_config_paths() -> list[Path]:
    return [Path.home() / ".config" / "fish" / "ai_help.yaml"]


def default_provider() -> str:
    return env_value("SHELP_MODEL_PROVIDER", "AI_HELP_MODEL_PROVIDER", default="gemini").strip().lower() or "gemini"


def default_model_for(provider: str) -> str:
    defaults = {
        "anthropic": env_value("SHELP_ANTHROPIC_MODEL", "AI_HELP_ANTHROPIC_MODEL", default="claude-sonnet-4-6"),
        "openai": env_value("SHELP_OPENAI_MODEL", "AI_HELP_OPENAI_MODEL", default="gpt-4.1-mini"),
        "gemini": env_value("SHELP_GEMINI_MODEL", "AI_HELP_GEMINI_MODEL", default="gemini-2.5-flash"),
    }
    return defaults[provider]


def load_yaml_config(path: Path) -> dict[str, str]:
    try:
        raw_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ShelpError(f"Unable to read config file at {path}: {exc}", stage="reading the helper config file") from exc
    except yaml.YAMLError as exc:
        raise ShelpError(f"Unable to parse config file at {path}: {exc}", stage="reading the helper config file") from exc

    if not isinstance(raw_data, dict):
        raise ShelpError(
            f"Config file at {path} must contain a mapping of keys to values.",
            stage="reading the helper config file",
        )

    return {str(key): "" if value is None else str(value) for key, value in raw_data.items()}


def load_config() -> dict[str, str]:
    primary = config_path()
    if primary.exists():
        return load_yaml_config(primary)

    for legacy_path in legacy_config_paths():
        if legacy_path.exists():
            return load_yaml_config(legacy_path)

    return {}


def save_config(config: dict[str, str]) -> None:
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = yaml.safe_dump(config, sort_keys=True, default_flow_style=False)
        path.write_text(serialized, encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError as exc:
        raise ShelpError(f"Unable to write config file at {path}: {exc}", stage="writing the helper config file") from exc


def migrate_legacy_config(*, force: bool = False) -> Path | None:
    primary = config_path()
    if primary.exists() and not force:
        return primary

    for legacy_path in legacy_config_paths():
        if legacy_path.exists():
            save_config(load_yaml_config(legacy_path))
            return primary

    return None


def normalize_provider_name(raw_value: str | None) -> str:
    provider = (raw_value or "").strip().lower()
    if not provider:
        provider = default_provider()
    if provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise ShelpError(
            f"Unsupported AI provider '{provider}'. Supported providers: {supported}.",
            stage="reading the helper config file",
        )
    return provider


def resolve_provider_name(config: dict[str, str]) -> str:
    return normalize_provider_name(
        config.get("provider")
        or config.get("model_provider")
        or env_value("SHELP_MODEL_PROVIDER", "AI_HELP_MODEL_PROVIDER")
        or default_provider()
    )


def resolve_model_name(config: dict[str, str], provider: str) -> str:
    generic_override = env_value("SHELP_MODEL", "AI_HELP_MODEL").strip()
    provider_override = env_value(f"SHELP_{provider.upper()}_MODEL", f"AI_HELP_{provider.upper()}_MODEL").strip()
    configured_model = config.get(f"{provider}_model", "").strip()
    return configured_model or generic_override or provider_override or default_model_for(provider)


def resolve_api_key_value(config: dict[str, str], provider: str) -> str:
    env_key_names = {
        "anthropic": ["ANTHROPIC_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    }[provider]

    candidate = config.get(f"{provider}_api_key", "").strip()
    if candidate:
        return candidate

    if provider == "anthropic":
        legacy_candidate = config.get("anthropic_api_key", "").strip()
        if legacy_candidate:
            return legacy_candidate

    for env_name in env_key_names:
        candidate = os.environ.get(env_name, "").strip()
        if candidate:
            return candidate

    return ""


def provider_api_env_hint(provider: str) -> str:
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY or GOOGLE_API_KEY",
    }[provider]


def ensure_provider_api_key(ui: "TerminalUI", config: dict[str, str], provider: str) -> str | None:
    existing_key = resolve_api_key_value(config, provider)
    if existing_key:
        return existing_key

    ui.agent_line(
        f"I do not have a {provider.title()} API key yet. Paste it here and I will save it to {config_path()}. I also check {provider_api_env_hint(provider)} in the environment.",
        "warning",
    )

    while True:
        try:
            candidate = ui.prompt_user()
        except EOFError:
            ui.agent_line(f"I did not receive a {provider.title()} API key, so I kept your existing configuration.", "warning")
            return None
        except KeyboardInterrupt:
            ui.agent_line(f"I stopped before saving a {provider.title()} API key, so I kept your existing configuration.", "warning")
            return None

        candidate = candidate.strip()
        if not candidate:
            ui.agent_line(f"I still need a non-empty {provider.title()} API key before I can switch to that provider.", "error")
            continue

        config[f"{provider}_api_key"] = candidate
        save_config(config)
        ui.agent_line(f"I saved your {provider.title()} API key to {config_path()}.", "success")
        return candidate


def resolve_provider_settings(ui: "TerminalUI") -> ProviderSettings | None:
    config = load_config()
    provider = resolve_provider_name(config)
    model = resolve_model_name(config, provider)
    stored_key = resolve_api_key_value(config, provider)
    if stored_key:
        return ProviderSettings(provider=provider, model=model, api_key=stored_key)

    ui.agent_line(
        f"I need your {provider.title()} API key before I can continue. Paste it here and I will save it to {config_path()}. I also look for {provider_api_env_hint(provider)} in the environment.",
        "warning",
    )

    while True:
        try:
            candidate = ui.prompt_user()
        except EOFError:
            ui.agent_line(f"I did not receive a {provider.title()} API key, so I am leaving your prompt unchanged.", "warning")
            return None
        except KeyboardInterrupt:
            ui.agent_line(f"I stopped before saving a {provider.title()} API key and left your prompt unchanged.", "warning")
            return None

        candidate = candidate.strip()
        if not candidate:
            ui.agent_line(f"I still need a non-empty {provider.title()} API key before I can continue.", "error")
            continue

        config[f"{provider}_api_key"] = candidate
        save_config(config)
        ui.agent_line(
            f"I saved your {provider.title()} API key to {config_path()} and I will prefer that file over the environment variable.",
            "success",
        )
        return ProviderSettings(provider=provider, model=model, api_key=candidate)
