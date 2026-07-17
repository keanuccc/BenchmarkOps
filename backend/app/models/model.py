"""Model Center ORM model — an LLM offering (e.g. via OpenRouter)."""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDMixin


class Model(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "models"

    name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(200), index=True)
    context_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pricing: Mapped[dict] = mapped_column(JSONType, default=dict)
    capabilities: Mapped[list] = mapped_column(JSONType, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
