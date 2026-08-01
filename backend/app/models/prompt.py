"""ORM model for the Prompt Library module."""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDMixin


class Prompt(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "prompts"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_prompts_project_name"),
    )

    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    template: Mapped[str] = mapped_column(Text)
    variables: Mapped[list] = mapped_column(JSONType, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
