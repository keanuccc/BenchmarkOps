"""Webhook subscription model for experiment lifecycle events."""
from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDMixin


class WebhookSubscription(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "webhook_subscriptions"

    organization_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(500))
    secret: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # e.g. ["experiment.completed", "experiment.failed"]
    events: Mapped[list] = mapped_column(JSONType, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
