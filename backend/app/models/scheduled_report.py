"""Scheduled report ORM model (continuous evaluation digest)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UTCDateTime, UUIDMixin

SCHEDULE_VALUES = ("daily", "weekly", "monthly")
REPORT_FORMAT_VALUES = ("md", "html", "pdf")


class ScheduledReport(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "scheduled_reports"
    __table_args__ = (
        CheckConstraint(
            "schedule IN ('daily', 'weekly', 'monthly')",
            name="ck_scheduled_reports_schedule",
        ),
        CheckConstraint(
            "format IN ('md', 'html', 'pdf')",
            name="ck_scheduled_reports_format",
        ),
    )

    organization_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    experiment_ids: Mapped[list] = mapped_column(JSONType, default=list)
    schedule: Mapped[str] = mapped_column(String(20), default="daily")
    format: Mapped[str] = mapped_column(String(10), default="md")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
