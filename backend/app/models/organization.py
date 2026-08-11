"""Organization and API-key models for multi-tenant isolation.

Each organization owns its own projects / datasets / benchmarks / prompts /
experiments / reports. Access is granted through role-scoped API keys:
owner / admin / member / viewer. The global ``settings.api_token`` and the
no-token demo mode remain supported: rows created outside an organization
context keep ``organization_id = NULL`` and are visible in that mode only.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Float, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin

ORG_STATUS_VALUES = ("active", "archived")
API_KEY_ROLES = ("owner", "admin", "member", "viewer")


class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')", name="ck_organizations_status"
        ),
    )

    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    # Optional cost guard used by the budget feature: cumulative evaluated cost
    # must stay below the cap before a new run may start.
    monthly_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)


class ApiKey(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="ck_api_keys_role",
        ),
    )

    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # SHA-256 of the raw key; the plaintext is shown exactly once at creation.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # First 8 chars of the raw key so users can recognize a key in listings.
    key_prefix: Mapped[str] = mapped_column(String(8))
    role: Mapped[str] = mapped_column(String(20), default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
