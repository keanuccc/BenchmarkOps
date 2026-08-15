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
            extra={"request_id": _request_id_var.get()},
        )


class TenantContextMiddleware:
    """Resolve auth and tenant context, and gate API reads in production.

    Development/demo mode keeps the original open-read behaviour. In production
    (``app_env=production``) with ``API_TOKEN`` set, every ``/api/v1`` request
    except the health/readiness probes must carry either the global token or a
    valid organization API key, including reads. This closes the gap where
    datasets/results could be enumerated anonymously while writes were guarded.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from app.core.config import settings
        from app.core.security import _resolve_org_key
        from app.core.tenant import (
            TenantContext,
            reset_tenant,
            set_tenant,
        )

        token = None
        credential: str | None = None
        auth_header = None
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth_header = value.decode("latin-1")
                break
        if auth_header and auth_header.lower().startswith("bearer "):
            credential = auth_header[7:].strip()

        # SSE's EventSource cannot send Authorization headers, so the endpoint
        # accepts ``?token=`` as an explicit fallback.
        if credential is None and scope.get("query_string"):
            from urllib.parse import parse_qs

            query = parse_qs(scope["query_string"].decode("latin-1"))
            credential = (query.get("token") or [None])[0]

        global_token_ok = bool(credential and settings.api_token and credential == settings.api_token)
        org_key_ok = False
        if credential and not global_token_ok:
            key = await _resolve_org_key(credential)
            if key is not None and key.is_active:
                token = set_tenant(
                    TenantContext(
                        organization_id=key.organization_id,
                        role=key.role,
                        key_id=key.id,
                    )
                )
                org_key_ok = True

        path = scope.get("path", "")
        production_read_gate = (
            settings.app_env.strip().lower() == "production"
            and bool(settings.api_token)
            and path.startswith("/api/v1")
            and path not in ("/api/v1/health", "/api/v1/ready")
        )
        if (
            scope.get("method") != "OPTIONS"
            and production_read_gate
            and not (global_token_ok or org_key_ok)
        ):
            await _send_unauthorized(send)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                try:
                    reset_tenant(token)
                except ValueError:
                    pass


async def _send_unauthorized(send) -> None:
    """Return a compact 401 JSON response from middleware."""
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b'{"detail":"Authentication required"}',
        }
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
    for handler in root.handlers:
        if not any(isinstance(f, RequestIDFilter) for f in handler.filters):
            handler.addFilter(RequestIDFilter())


def ensure_request_id_logging() -> None:
    """Re-attach the RequestIDFilter after uvicorn's logging reconfiguration.

    uvicorn applies ``logging.config.dictConfig`` after app import, which drops
    logger-level filters. Handler-level filters survive that reset, so re-ensure
    both at startup (called from the app lifespan).
    """
    root = logging.getLogger()
    if not any(isinstance(f, RequestIDFilter) for f in root.filters):
        root.addFilter(RequestIDFilter())
    for handler in root.handlers:
        if not any(isinstance(f, RequestIDFilter) for f in handler.filters):
            handler.addFilter(RequestIDFilter())


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
