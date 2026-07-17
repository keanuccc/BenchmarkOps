"""Pydantic schemas for the Dataset Center module."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DatasetCreate(BaseModel):
    project_id: str
    name: str
    description: str | None = None
    tags: list[str] | None = None


class DatasetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class DatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    description: str | None
    format: str
    version: int
    row_count: int
    tags: list
    stats: dict
    column_schema: list
    created_at: datetime
    updated_at: datetime


class DatasetRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    idx: int
    input: dict
    expected: dict | None
