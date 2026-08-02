"""Append-only audit events for dataset governance."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, UTCDateTime, UUIDMixin


class AuditEvent(Base, UUIDMixin):
    __tablename__ = "audit_events"

    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(50))
    actor: Mapped[str | None] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
