"""Minimal global token auth.

A single shared token (``settings.api_token``) gates write operations. This is a
conservative fix for the "zero auth — anyone can mutate data" audit finding. It is
NOT a full user/tenant system: an empty token disables enforcement entirely so the
offline Mock demo keeps running untouched.

When a token is configured, clients must send ``Authorization: Bearer <token>`` on
write requests. Read endpoints (GET, health, analytics, compare) are intentionally
left open so anonymous browsing in the demo still works.
"""
from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.exceptions import UnauthorizedError

_bearer = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Guard dependency for write endpoints.

    Empty ``settings.api_token`` -> always pass (demo/Mock mode).
    Configured token -> require ``Bearer <token>``; missing/wrong -> 401.
    """
    if not settings.api_token:
        return

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Missing or malformed Authorization header")
    if credentials.credentials != settings.api_token:
        raise UnauthorizedError("Invalid API token")
