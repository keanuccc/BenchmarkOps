"""Pydantic schemas for the Benchmark module."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

BENCHMARK_TYPES = {"qa", "coding", "agent", "classification", "generation"}


class BenchmarkCreate(BaseModel):
    project_id: str
    name: str
    type: str
    description: str | None = None
    metric: str | None = None
    metric_config: dict = {}

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in BENCHMARK_TYPES:
            raise ValueError(
                f"Invalid benchmark type {v!r}; expected one of {sorted(BENCHMARK_TYPES)}"
            )
        return v

    @field_validator("metric_config")
    @classmethod
    def _validate_config(cls, v: dict) -> dict:
        return v if v is not None else {}


class BenchmarkUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    type: str | None = None
    metric: str | None = None
    metric_config: dict | None = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str | None) -> str | None:
        if v is not None and v not in BENCHMARK_TYPES:
            raise ValueError(
                f"Invalid benchmark type {v!r}; expected one of {sorted(BENCHMARK_TYPES)}"
            )
        return v


class BenchmarkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    description: str | None
    type: str
    metric: str
    metric_config: dict
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime
