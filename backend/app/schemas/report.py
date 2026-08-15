"""Pydantic v2 DTOs for the AI Report module."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReportGenerateRequest(BaseModel):
    project_id: str
    experiment_ids: list[str] = Field(default_factory=list)
    title: str | None = None
    statistics: dict | None = None


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    title: str
    experiment_ids: list
    content_markdown: str
    sections: dict
    generated_by: str
    created_at: datetime
    updated_at: datetime
