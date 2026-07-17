"""Benchmark ORM model."""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDMixin


class Benchmark(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "benchmarks"

    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(30))
    metric: Mapped[str] = mapped_column(String(50))
    metric_config: Mapped[dict] = mapped_column(JSONType, default=dict)
