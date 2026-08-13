"""Application configuration via pydantic-settings.

All runtime configuration is sourced from environment variables / .env — no
hardcoded values in business logic. Swapping SQLite -> Postgres or enabling the
OpenRouter provider is purely a config change.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_name: str = "BenchmarkOps"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Auth: empty -> no auth enforced (demo/Mock mode); set a value to require Bearer token.
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
    # provider. DeepSeek is the cheapest strong domestic gateway, so it is the
    # default. Allowed: deepseek|openrouter|qiniu|mock.
    default_provider: str = "deepseek"

    # DeepSeek official API (OpenAI-compatible, domestic + low cost). Empty key ->
    # provider disabled (Mock fallback unless explicitly requested). The key lives
    # only in .env, which is git-ignored; never hardcode it here.
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    # Qiniu Cloud AI Token API (OpenAI-compatible), the second gateway. Empty key ->
    # provider disabled (Mock fallback unless explicitly requested). The key lives only
    # in .env, which is git-ignored; never hardcode it here.
    qiniu_api_key: str = ""
    qiniu_base_url: str = "https://api.qnaigc.com/v1"
    # Qiniu platform RPM cap per API key is 75. This local token-bucket cap mirrors
    # that ceiling so the runner throttles before the upstream starts returning 429s.
    qiniu_rpm_cap: int = 75
    qiniu_rpd_cap: int = 5000
    # Comma-separated Qiniu model ids that are free-tier (need token-bucket throttle
    # even without a ":free" suffix). Complements the conventional ":free" marker.
    qiniu_free_models: str = ""

    # Evaluation runner
    eval_max_workers: int = 4
    eval_request_timeout: int = 60
    # Persist scored rows in batches of this size instead of buffering every
    # row in memory until the run finishes.
    eval_result_batch_size: int = 100

    # AI report generation: model id + optional provider for the LLM that writes
    # reports. Empty model id falls back to the report service default; empty
    # provider routes through the configured default gateway.
    report_model_id: str = ""
    report_provider: str = ""

    # Free-model throttle: cap in-flight rows per run. With Qiniu RPM=75, a concurrency
    # of 5 keeps batch fan-out moderate so the provider-layer token bucket can smooth
    # the send rate without tripping the upstream rate limiter.
    free_model_concurrency: int = 5
    free_model_rpm_cap: int = 300

    # Task queue backend: "asyncio" (in-process, default) or "arq" (Redis-backed
    # distributed queue consumed by `app.worker.WorkerSettings` workers).
    task_queue_backend: str = "asyncio"

    # ARQ / Redis settings (only used when task_queue_backend == "arq").
    redis_dsn: str = "redis://localhost:6379/0"
    # Max attempts per job: 2 = one initial attempt + one retry. ARQ only retries
    # when the job function raises arq.Retry (wired to RetryableTaskError).
    task_max_tries: int = 2
    # Seconds to wait before retrying a transient (pre-billing) failure.
    task_retry_after: int = 30
    # Overall timeout for one job attempt; evaluation runs are long, so this is
    # a safety valve rather than a working limit.
    task_job_timeout: int = 86400

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
        return (
            bool(self.deepseek_api_key.strip())
            or bool(self.openrouter_api_key.strip())
            or bool(self.qiniu_api_key.strip())
        )

    @property
    def auth_enabled(self) -> bool:
        """True when a global API token is set (auth enforced on write endpoints)."""
        return bool(self.api_token.strip())

    @model_validator(mode="after")
    def _production_requires_api_token(self) -> "Settings":
        """A production deployment must never silently run without auth."""
        if self.app_env.strip().lower() == "production" and not self.api_token.strip():
            raise ValueError("API_TOKEN is required when app_env=production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
