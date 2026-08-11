"""Pydantic schemas for organizations and API keys."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

API_KEY_ROLES = ("owner", "admin", "member", "viewer")


class OrganizationCreate(BaseModel):
    name: str
    description: str | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    monthly_budget_usd: float | None = None


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    status: str
    monthly_budget_usd: float | None
    created_at: datetime
    updated_at: datetime


class ApiKeyCreate(BaseModel):
    name: str
    role: str = "member"

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in API_KEY_ROLES:
            raise ValueError(
                f"Invalid role {v!r}; expected one of {sorted(API_KEY_ROLES)}"
            )
        if v == "owner":
            raise ValueError("owner keys can only be generated when creating an organization")
        return v


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    name: str
    key_prefix: str
    role: str
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """ApiKeyRead plus the one-time plaintext key."""

    key: str


class OrganizationWithKey(BaseModel):
    organization: OrganizationRead
    api_key: ApiKeyCreated
