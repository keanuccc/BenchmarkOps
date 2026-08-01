"""Request ID middleware + structured logging for observability.

Adds a unique request_id to every HTTP request (X-Request-ID header + log
records) and exposes basic metrics via /metrics endpoint.
"""
from __future__ import annotations

import contextvars
import logging
import time
import uuid
from typing import Any

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIDFilter(logging.Filter):
    """Attach the current request_id (from context) to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()  # type: ignore[attr-defined]
        return True


class RequestIDMiddleware:
    """ASGI middleware that assigns a unique request_id to each HTTP request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex[:12]
        start_time = time.perf_counter()
        token = _request_id_var.set(request_id)

        async def _send(message: dict) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            _request_id_var.reset(token)

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
        logging.getLogger("benchmarkops.middleware").info(
            "%s %s completed in %.1fms",
            scope.get("method", "?"),
            scope.get("path", "?"),
            elapsed_ms,
        )


def setup_structured_logging() -> None:
    """Configure structured logging with request_id in every record."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
    )
    root = logging.getLogger()
    if not any(isinstance(f, RequestIDFilter) for f in root.filters):
        root.addFilter(RequestIDFilter())


def get_metrics_summary() -> dict[str, Any]:
    """Return basic application metrics (no Prometheus client required)."""
    import platform
    from pathlib import Path

    from app.core.config import settings

    # Count DB files
    db_path = Path(settings.database_url.split("///", 1)[-1]) if settings.database_url.startswith("sqlite") else None
    db_size_mb = round(db_path.stat().st_size / (1024 * 1024), 2) if db_path and db_path.exists() else 0

    # Backup count
    backup_dir = Path("./backups")
    backup_count = len(list(backup_dir.glob("*.db"))) if backup_dir.exists() else 0

    return {
        "app": settings.app_name,
        "env": settings.app_env,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "database": {
            "backend": "SQLite" if settings.database_url.startswith("sqlite") else "PostgreSQL",
            "size_mb": db_size_mb,
            "backup_count": backup_count,
        },
        "auth_enabled": settings.auth_enabled,
        "provider_enabled": settings.provider_enabled,
        "uptime_estimate": "unknown",  # No process start tracking in v1
    }
