"""Pydantic schemas for the Model Center module."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ModelCreate(BaseModel):
    name: str
    provider: str
    model_id: str
    context_length: int | None = None
    pricing: dict = {}
    capabilities: list = []
    is_active: bool = True


class ModelUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    model_id: str | None = None
    context_length: int | None = None
    pricing: dict | None = None
    capabilities: list | None = None
    is_active: bool | None = None


class ModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    provider: str
    model_id: str
    context_length: int | None
    pricing: dict
    capabilities: list
    is_active: bool
    created_at: datetime
    updated_at: datetime
