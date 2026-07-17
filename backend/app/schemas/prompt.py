"""Pydantic schemas for the Prompt Library module."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PromptCreate(BaseModel):
    project_id: str
    name: str
    template: str
    description: str | None = None


class PromptUpdate(BaseModel):
    name: str | None = None
    template: str | None = None
    description: str | None = None


class PromptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    template: str
    variables: list
    version: int
    description: str | None
    created_at: datetime
    updated_at: datetime
