"""Per-request organization context (contextvars).

The authenticated API key (or the absence of one) decides which organization a
request belongs to. Repository code reads this context so every scoped query
is filtered automatically; services and routes do not need to thread the
organization id through every call. Background tasks (evaluation runner) run
outside any request context and therefore see unscoped rows by design.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    organization_id: str
    role: str  # owner | admin | member | viewer
    key_id: str


_tenant_var: ContextVar[TenantContext | None] = ContextVar(
    "benchmarkops_tenant", default=None
)


def get_tenant() -> TenantContext | None:
    return _tenant_var.get()


def set_tenant(context: TenantContext | None) -> Token:
    """Set the tenant for the current request task; returns a reset token."""
    return _tenant_var.set(context)


def reset_tenant(token: Token) -> None:
    _tenant_var.reset(token)
