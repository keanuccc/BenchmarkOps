"""Pydantic schemas for webhook subscriptions."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_EVENTS = ("experiment.completed", "experiment.failed")


class WebhookCreate(BaseModel):
    project_id: str
    name: str
    url: str
    secret: str | None = None
    events: list[str] = Field(default_factory=lambda: ["experiment.completed"])

    @field_validator("events")
    @classmethod
    def _validate_events(cls, v: list[str]) -> list[str]:
        for event in v:
            if event not in ALLOWED_EVENTS:
                raise ValueError(
                    f"Unsupported event {event!r}; expected one of {ALLOWED_EVENTS}"
                )
        return v


class WebhookUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    secret: str | None = None
    events: list[str] | None = None
    is_active: bool | None = None


class WebhookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    url: str
    events: list
    is_active: bool
    created_at: datetime
    updated_at: datetime
