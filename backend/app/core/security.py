"""Authentication and organization-scoped authorization.

Three modes, in priority order:

1. Organization API key (``Bearer <org-key>``): the key is looked up in the
   ``api_keys`` table, its role gates writes (viewer is read-only), and the
   request runs inside that organization's tenant context.
2. Legacy global ``settings.api_token``: matches the single shared token and
   runs without tenant scope (legacy/demo deployments).
3. No token configured: everything is open and unscoped so the offline Mock
   demo keeps working untouched.

Read endpoints stay open for anonymous browsing; write endpoints require a
credential when any credential is configured, and organization keys with the
``viewer`` role are rejected on writes.
"""
from __future__ import annotations

import hashlib

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.tenant import TenantContext, set_tenant
from app.models.organization import ApiKey

_bearer = HTTPBearer(auto_error=False)


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def _resolve_org_key(raw_key: str) -> ApiKey | None:
    """Look up an organization API key by its SHA-256 hash."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == _hash_key(raw_key))
        )
        return result.scalar_one_or_none()


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TenantContext | None:
    """Resolve the request's tenant context from its bearer credential.

    Returns ``None`` for the legacy global token and for the no-token demo
    mode (both run unscoped). Raises 401 for an unknown credential.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    raw = credentials.credentials
    if settings.api_token and raw == settings.api_token:
        return None
    key = await _resolve_org_key(raw)
    if key is None:
        if settings.api_token:
            raise UnauthorizedError("Invalid API token")
        raise UnauthorizedError("Invalid API key")
    if not key.is_active:
        raise UnauthorizedError("API key is deactivated")
    return TenantContext(
        organization_id=key.organization_id,
        role=key.role,
        key_id=key.id,
    )


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Guard dependency for write endpoints.

    - No credential + no global token: pass (demo mode).
    - Organization key: pass for owner/admin/member, 403 for viewer; the
      tenant context is installed for the rest of the request.
    - Global token: pass unscoped (legacy mode).
    - Unknown credential: 401.
    """
    context = await get_auth_context(credentials)
    if context is not None:
        if context.role == "viewer":
            raise ForbiddenError("Viewer API keys are read-only")
        set_tenant(context)
        return
    # No organization key: enforce the legacy global token when configured.
    if settings.api_token:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise UnauthorizedError("Missing or malformed Authorization header")
        if credentials.credentials != settings.api_token:
            raise UnauthorizedError("Invalid API token")


async def require_org_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TenantContext:
    """Require an organization API key (any role) and install its tenant scope."""
    context = await get_auth_context(credentials)
    if context is None:
        raise UnauthorizedError("An organization API key is required")
    set_tenant(context)
    return context


async def require_org_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TenantContext:
    """Require an organization key with owner or admin role."""
    context = await require_org_auth(credentials)
    if context.role not in ("owner", "admin"):
        raise ForbiddenError("Owner or admin role required")
    return context
