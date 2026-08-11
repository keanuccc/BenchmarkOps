"""Pydantic schemas for scheduled reports."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEDULE_VALUES = ("daily", "weekly", "monthly")
REPORT_FORMAT_VALUES = ("md", "html", "pdf")


class ScheduledReportCreate(BaseModel):
    project_id: str
    name: str
    experiment_ids: list[str] = Field(default_factory=list)
    schedule: str = "daily"
    format: str = "md"

    @field_validator("schedule")
    @classmethod
    def _validate_schedule(cls, v: str) -> str:
        if v not in SCHEDULE_VALUES:
            raise ValueError(f"schedule must be one of {SCHEDULE_VALUES}")
        return v

    @field_validator("format")
    @classmethod
    def _validate_format(cls, v: str) -> str:
        if v not in REPORT_FORMAT_VALUES:
            raise ValueError(f"format must be one of {REPORT_FORMAT_VALUES}")
        return v


class ScheduledReportUpdate(BaseModel):
    name: str | None = None
    experiment_ids: list[str] | None = None
    schedule: str | None = None
    format: str | None = None
    is_active: bool | None = None


class ScheduledReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    experiment_ids: list
    schedule: str
    format: str
    is_active: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    created_at: datetime
    updated_at: datetime
