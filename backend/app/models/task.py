"""Persistent evaluation task records (audit + startup recovery)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class EvaluationTask(Base, UUIDMixin, TimestampMixin):
    """One row per run submission.

    The in-process task queue owns execution; this table is an append-only
    audit trail (who queued what, when it ran, and how it ended) that also
    lets startup recovery mark tasks failed consistently with experiments.
    """

    __tablename__ = "evaluation_tasks"

    experiment_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(20), default="run")  # run | retry
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued | running | succeeded | failed | cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
