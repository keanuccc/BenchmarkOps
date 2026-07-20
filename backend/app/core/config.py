"""Application configuration via pydantic-settings.

All runtime configuration is sourced from environment variables / .env — no
hardcoded values in business logic. Swapping SQLite -> Postgres or enabling the
OpenRouter provider is purely a config change.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_name: str = "BenchmarkOps"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Auth (empty -> no auth enforced, demo/Mock mode; set a value to enable global token auth)
    api_token: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./benchmarkops.db"

    # CORS (comma-separated list of allowed browser origins)
    backend_cors_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002"

    # OpenRouter provider (empty key -> Mock provider)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_http_referer: str = "http://localhost:3000"
    openrouter_app_title: str = "BenchmarkOps"

    # Evaluation runner
    eval_max_workers: int = 4
    eval_request_timeout: int = 60

    # Free-model throttle (measured, not assumed): probing showed tencent/hy3:free
    # sustains ~10 concurrent requests with zero 429 and RPM >= 325. We therefore do
    # NOT space calls with a fixed sleep; instead we cap in-flight rows per run
    # (free_model_concurrency) and cap overall send rate via a token bucket
    # (free_model_rpm_cap), both well under the measured ceiling for headroom.
    free_model_concurrency: int = 8
    free_model_rpm_cap: int = 300

    # Dataset upload limits (resource-exhaustion protection)
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_dataset_rows: int = 100_000

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]

    @property
    def provider_enabled(self) -> bool:
        """True when a real provider key is configured; else Mock is used."""
        return bool(self.openrouter_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
