"""ORM model for the Prompt Library module."""
from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDMixin


class Prompt(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "prompts"

    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    template: Mapped[str] = mapped_column(Text)
    variables: Mapped[list] = mapped_column(JSONType, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str | None] = mapped_column(Text)
