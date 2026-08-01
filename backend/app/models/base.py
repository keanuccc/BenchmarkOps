"""Declarative base + shared mixins for all ORM models.

- UUID string primary keys (portable across SQLite/Postgres).
- created_at / updated_at timestamps (always UTC-aware in Python).
- A JSON type alias that works on both SQLite and Postgres.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator

# Portable JSON column type (SQLAlchemy maps to JSON on SQLite, JSONB-capable on PG).
JSONType = JSON


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes that behave identically on SQLite/Postgres.

    SQLite has no native timezone-aware column type: aware values are stored as
    naive UTC strings, and every value read back is normalized to an aware UTC
    datetime. Postgres keeps its native timestamptz behaviour.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        if dialect.name == "sqlite":
            # SQLite stores naive ISO strings; UTC is the canonical frame.
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid, index=True
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=_now, onupdate=_now, nullable=False
    )
