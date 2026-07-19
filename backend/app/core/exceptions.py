"""Domain exceptions and their HTTP mapping.

Services raise domain exceptions; a single FastAPI exception handler maps them to
HTTP responses, keeping routers thin and business logic transport-agnostic.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Base class for all business-rule errors."""

    status_code: int = 400
    code: str = "domain_error"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class ValidationError(DomainError):
    status_code = 422
    code = "validation_error"


class UnauthorizedError(DomainError):
    status_code = 401
    code = "unauthorized"


class ProviderError(DomainError):
    """Base class for upstream model-gateway failures.

    Surfaced to clients as 502 (bad gateway) since the failure originates from the
    LLM provider we proxy to, not from client input.
    """

    status_code = 502
    code = "provider_error"


class RateLimitedError(DomainError):
    """Upstream is rate-limiting us (HTTP 429) and the caller should back off."""

    status_code = 429
    code = "provider_rate_limited"


async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Catch-all for any non-DomainError exception.

    Returns a generic 500 with no stack trace or internal detail so we don't leak
    SQL, filesystem paths, or other diagnostics to clients. The exception is still
    logged server-side for diagnostics.
    """
    logging.getLogger(__name__).exception("Unhandled exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Internal server error"}},
    )


def register_exception_handlers(app) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
