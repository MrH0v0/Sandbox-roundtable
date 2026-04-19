from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values, load_dotenv, set_key
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AppSettings(BaseModel):
    """Runtime settings loaded from environment variables."""

    project_root: Path = PROJECT_ROOT
    aihubmix_base_url: str = "https://api.aihubmix.com/v1"
    aihubmix_api_key: str | None = None
    request_timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    retry_backoff_seconds: float = Field(default=1.0, ge=0.0)
    skills_dir: Path = PROJECT_ROOT / "skills"
    configs_dir: Path = PROJECT_ROOT / "configs"
    sessions_dir: Path = PROJECT_ROOT / "sessions"


class ApiSettingsUpdate(BaseModel):
    """Editable API settings persisted through the existing .env chain."""

    provider_label: str = "AIHubMix"
    base_url: str = "https://api.aihubmix.com/v1"
    api_key: str = ""
    requires_restart: bool = True


def _resolve_runtime_path(path_value: str | None, default_dir_name: str) -> Path:
    candidate = Path(path_value) if path_value else PROJECT_ROOT / default_dir_name
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate


def _build_settings_from_env(values: dict[str, str]) -> AppSettings:
    return AppSettings(
        aihubmix_base_url=values.get("AIHUBMIX_BASE_URL", "https://api.aihubmix.com/v1"),
        aihubmix_api_key=values.get("AIHUBMIX_API_KEY") or None,
        request_timeout_seconds=float(values.get("AIHUBMIX_REQUEST_TIMEOUT_SECONDS", "60")),
        max_retries=int(values.get("AIHUBMIX_MAX_RETRIES", "2")),
        retry_backoff_seconds=float(values.get("AIHUBMIX_RETRY_BACKOFF_SECONDS", "1.0")),
        skills_dir=_resolve_runtime_path(values.get("SANDBOX_SKILLS_DIR"), "skills"),
        configs_dir=_resolve_runtime_path(values.get("SANDBOX_CONFIGS_DIR"), "configs"),
        sessions_dir=_resolve_runtime_path(values.get("SANDBOX_SESSIONS_DIR"), "sessions"),
    )


def get_env_file_path() -> Path:
    return PROJECT_ROOT / ".env"


def _read_env_values(env_path: Path | None = None) -> dict[str, str]:
    path = env_path or get_env_file_path()
    if not path.exists():
        return {}
    raw_values = dotenv_values(path)
    return {key: str(value) for key, value in raw_values.items() if value is not None}


def load_api_settings(env_path: Path | None = None) -> ApiSettingsUpdate:
    values = _read_env_values(env_path)
    base_url = values.get("AIHUBMIX_BASE_URL", "https://api.aihubmix.com/v1").strip()
    provider_label = "AIHubMix" if "aihubmix.com" in base_url.lower() else "自定义 OpenAI 兼容接口"
    return ApiSettingsUpdate(
        provider_label=provider_label,
        base_url=base_url,
        api_key=values.get("AIHUBMIX_API_KEY", "").strip(),
    )


def save_api_settings(update: ApiSettingsUpdate, env_path: Path | None = None) -> AppSettings:
    path = env_path or get_env_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")

    set_key(str(path), "AIHUBMIX_BASE_URL", update.base_url.strip())
    set_key(str(path), "AIHUBMIX_API_KEY", update.api_key.strip())

    load_settings.cache_clear()
    if path == get_env_file_path():
        return load_settings()
    return _build_settings_from_env(_read_env_values(path))


@lru_cache(maxsize=1)
def load_settings() -> AppSettings:
    """Load environment variables once and reuse them for the app lifetime."""

    load_dotenv(get_env_file_path(), override=True)
    return _build_settings_from_env(
        {
            "AIHUBMIX_BASE_URL": os.getenv("AIHUBMIX_BASE_URL", "https://api.aihubmix.com/v1"),
            "AIHUBMIX_API_KEY": os.getenv("AIHUBMIX_API_KEY", ""),
            "AIHUBMIX_REQUEST_TIMEOUT_SECONDS": os.getenv("AIHUBMIX_REQUEST_TIMEOUT_SECONDS", "60"),
            "AIHUBMIX_MAX_RETRIES": os.getenv("AIHUBMIX_MAX_RETRIES", "2"),
            "AIHUBMIX_RETRY_BACKOFF_SECONDS": os.getenv("AIHUBMIX_RETRY_BACKOFF_SECONDS", "1.0"),
            "SANDBOX_SKILLS_DIR": os.getenv("SANDBOX_SKILLS_DIR", ""),
            "SANDBOX_CONFIGS_DIR": os.getenv("SANDBOX_CONFIGS_DIR", ""),
            "SANDBOX_SESSIONS_DIR": os.getenv("SANDBOX_SESSIONS_DIR", ""),
        }
    )


def ensure_runtime_directories(settings: AppSettings) -> None:
    """Create data directories if they are missing."""

    settings.skills_dir.mkdir(parents=True, exist_ok=True)
    settings.configs_dir.mkdir(parents=True, exist_ok=True)
    settings.sessions_dir.mkdir(parents=True, exist_ok=True)
