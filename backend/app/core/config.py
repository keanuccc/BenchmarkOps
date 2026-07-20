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

    # Provider routing. The default gateway used when a model does not pin its own
    # provider. User wants Qiniu AI as the default gateway. Allowed: openrouter|qiniu|mock.
    default_provider: str = "qiniu"

    # Qiniu Cloud AI Token API (OpenAI-compatible), the second gateway. Empty key ->
    # provider disabled (Mock fallback unless explicitly requested). The key lives only
    # in .env, which is git-ignored; never hardcode it here.
    qiniu_api_key: str = ""
    qiniu_base_url: str = "https://api.qnaigc.com/v1"
    # RPM / RPD token-bucket caps for Qiniu. Qiniu has no global fixed RPM/RPD — the
    # real ceiling is the per-API-key invisible rate window (free/basic tiers hit
    # "rate limit reached for RPM" around ~15-40 RPM, confirmed from request logs).
    # These are LOCAL safety caps sized BELOW that window so the bucket throttles
    # locally instead of wasting calls on 429s. Start conservative; raise gradually
    # while watching 请求日志.csv for 429s to find the true ceiling.
    qiniu_rpm_cap: int = 15
    qiniu_rpd_cap: int = 5000
    # Comma-separated Qiniu model ids that are free-tier (need token-bucket throttle
    # even without a ":free" suffix). Complements the conventional ":free" marker.
    qiniu_free_models: str = ""

    # Evaluation runner
    eval_max_workers: int = 4
    eval_request_timeout: int = 60

    # Free-model throttle: cap in-flight rows per run. Lowered to 3 so a single
    # experiment does not fire 8 concurrent calls in one instant and trip Qiniu's
    # invisible per-key RPM window (observed 429s in 请求日志.csv at higher burst).
    free_model_concurrency: int = 3
    free_model_rpm_cap: int = 300

    # Dataset upload limits (resource-exhaustion protection)
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_dataset_rows: int = 100_000

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]

    @property
    def qiniu_free_set(self) -> set[str]:
        """Parsed set of free-tier Qiniu model ids (from qiniu_free_models)."""
        return {m.strip() for m in self.qiniu_free_models.split(",") if m.strip()}

    @property
    def provider_enabled(self) -> bool:
        """True when any real provider key is configured; else Mock is used."""
        return bool(self.openrouter_api_key.strip()) or bool(self.qiniu_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
