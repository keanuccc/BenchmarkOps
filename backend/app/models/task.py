"""Persistent evaluation task records (audit + startup recovery)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDMixin


class EvaluationTask(Base, UUIDMixin, TimestampMixin):
    """One row per run submission.

    The in-process task queue owns execution; this table is an audit/lifecycle
    record (who queued what, when it ran, and how it ended) that also lets
    startup recovery mark tasks failed consistently with experiments.

    Rows are never hard-deleted: when the owning experiment is deleted,
    ``experiment_deleted_at`` is set so the audit trail survives while queries
    can still tell the experiment no longer exists.
    """

    __tablename__ = "evaluation_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_evaluation_tasks_status",
        ),
        CheckConstraint(
            "action IN ('run', 'retry')", name="ck_evaluation_tasks_action"
        ),
    )

    experiment_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(20), default="run")  # run | retry
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued | running | succeeded | failed | cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    experiment_deleted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
