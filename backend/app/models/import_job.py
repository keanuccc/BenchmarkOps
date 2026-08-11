"""Background dataset import jobs (async ingest with progress and retry safety)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UTCDateTime, UUIDMixin


class ImportJob(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "import_jobs"

    project_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    dataset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    format: Mapped[str] = mapped_column(String(10))
    mode: Mapped[str] = mapped_column(String(20), default="create")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued | running | succeeded | failed | cancelled
    idempotency_key: Mapped[str | None] = mapped_column(String(128), index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    source_filename: Mapped[str | None] = mapped_column(Text)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    error_rows: Mapped[list] = mapped_column(JSONType, default=list)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
