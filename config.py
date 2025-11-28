"""Configuration helpers for the Zoo Voice AI testing utilities."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when required configuration is missing."""


_PROJECT_ROOT = Path(__file__).resolve().parent
# Load project-specific .env first, then fall back to default search path.
_ENV_FILE_LOADED: Final[bool] = load_dotenv(_PROJECT_ROOT / ".env", override=True)
_DEFAULT_ENV_LOADED: Final[bool] = load_dotenv(override=True)


@dataclass(frozen=True)
class AzureConfig:
    """Azure Speech configuration."""

    key: str
    region: str
    voice: str


@dataclass(frozen=True)
class ChatbaseConfig:
    """Chatbase API configuration."""

    api_key: str
    bot_id: str
    api_url: str


@dataclass(frozen=True)
class GCPConfig:
    """Google Cloud configuration."""

    credentials_path: Path


_DEFAULT_ENV_VARS: Final[tuple[str, ...]] = (
    "AZURE_SPEECH_KEY",
    "AZURE_SPEECH_REGION",
    "AZURE_TTS_VOICE",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "CHATBASE_API_KEY",
    "CHATBASE_BOT_ID",
    "CHATBASE_API_URL",
    "DEFAULT_LANGUAGE_CODE",
    "OPENAI_API_KEY",
)


def _require_env(var_name: str) -> str:
    """Return the required environment variable or raise an error."""

    value = os.getenv(var_name)
    if value is None or value.strip() == "":
        raise ConfigError(
            f"Environment variable '{var_name}' is required but was not provided."
        )
    return value.strip()


def get_azure_config() -> AzureConfig:
    """Return Azure Speech credentials and default voice."""

    key = _require_env("AZURE_SPEECH_KEY")
    region = _require_env("AZURE_SPEECH_REGION")
    voice = _require_env("AZURE_TTS_VOICE")
    return AzureConfig(key=key, region=region, voice=voice)


def get_chatbase_config() -> ChatbaseConfig:
    """Return Chatbase API configuration."""

    api_key = _require_env("CHATBASE_API_KEY")
    bot_id = _require_env("CHATBASE_BOT_ID")
    api_url = _require_env("CHATBASE_API_URL")
    return ChatbaseConfig(api_key=api_key, bot_id=bot_id, api_url=api_url)


def get_gcp_config() -> GCPConfig:
    """Return Google Cloud credentials configuration."""

    credentials = Path(_require_env("GOOGLE_APPLICATION_CREDENTIALS")).expanduser()
    if not credentials.exists():
        raise ConfigError(
            "GOOGLE_APPLICATION_CREDENTIALS points to a missing file: "
            f"{credentials}"
        )
    return GCPConfig(credentials_path=credentials)


def get_default_language_code() -> str:
    """Return the default language code for STT requests."""

    return _require_env("DEFAULT_LANGUAGE_CODE")


@dataclass(frozen=True)
class OpenAIConfig:
    """OpenAI API configuration."""

    api_key: str


def get_openai_config() -> OpenAIConfig:
    """Return OpenAI API configuration."""

    api_key = _require_env("OPENAI_API_KEY")
    return OpenAIConfig(api_key=api_key)


__all__ = [
    "AzureConfig",
    "ChatbaseConfig",
    "ConfigError",
    "GCPConfig",
    "OpenAIConfig",
    "get_azure_config",
    "get_chatbase_config",
    "get_default_language_code",
    "get_gcp_config",
    "get_openai_config",
]
