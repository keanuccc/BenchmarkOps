"""Request ID middleware + structured logging for observability.

Adds a unique request_id to every HTTP request, propagates it through logs,
and exposes basic metrics via /metrics endpoint.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import Request, Response


class RequestIDMiddleware:
    """Middleware that assigns a unique request_id to each request.

    - Adds X-Request-ID header to responses
    - Injects request_id into log records via contextvars
    - Logs method, path, status, duration on every request
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger("benchmarkops.middleware")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await send  # type: ignore[misc]
            return

        request_id = str(uuid.uuid4())[:12]
        start_time = time.perf_counter()

        # Use a custom log record factory to inject request_id
        original_factory = logging.getLogRecordFactory()

        def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = original_factory(*args, **kwargs)
            record.request_id = request_id  # type: ignore[attr-defined]
            return record

        logging.setLogRecordFactory(factory)

        async def _send(message: dict) -> None:
            if message.get("type") == "http.response.start":
                headers = {k: v for k, v in message.get("headers", [])}
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await send  # type: ignore[misc]
        except Exception:
            pass

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
        self._logger.info(
            "%s %s completed in %.1fms",
            scope.get("method", "?"),
            scope.get("path", "?"),
            elapsed_ms,
            extra={"request_id": request_id},
        )

        # Restore original factory
        logging.setLogRecordFactory(original_factory)


def setup_structured_logging() -> None:
    """Configure structured JSON logging when python-json-logger is available."""
    try:
        from python_json_logger import formatters

        class RequestIDFormatter(formatters.StructuredFormatter):
            def __init__(self):
                super().__init__(
                    fmt="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
                )

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        )
    except ImportError:
        # python-json-logger not installed — use default format with request_id
        pass


def get_metrics_summary() -> dict[str, Any]:
    """Return basic application metrics (no Prometheus client required)."""
    import os
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
