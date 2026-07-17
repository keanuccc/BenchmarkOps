"""Declarative base + shared mixins for all ORM models.

- UUID string primary keys (portable across SQLite/Postgres).
- created_at / updated_at timestamps.
- A JSON type alias that works on both SQLite and Postgres.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

# Portable JSON column type (SQLAlchemy maps to JSON on SQLite, JSONB-capable on PG).
JSONType = JSON


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid, index=True
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
