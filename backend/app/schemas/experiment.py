"""Pydantic v2 DTOs for the Experiment module."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Error strings persisted in DB are internal diagnostics (raw exception text) and may
# contain SQL, filesystem paths, or other sensitive detail. Redact them before they
# reach clients: keep only the exception type and a short, detail-free summary.
def _sanitize_error(value: str | None) -> str | None:
    if not value:
        return value
    # First line is the message; the head (before ":") is usually the exception type.
    first_line = value.splitlines()[0] if value.splitlines() else value
    etype = first_line.split(":", 1)[0].strip()
    safe = etype if etype and etype != first_line.strip() else "evaluation_error"
    return f"{safe} (details in server logs)"[:80]


class ExperimentCreate(BaseModel):
    project_id: str
    name: str
    dataset_id: str
    benchmark_id: str
    prompt_id: str
    model_id: str  # DB id of a Model row
    params: dict = Field(default_factory=dict)


class ExperimentUpdate(BaseModel):
    name: str | None = None
    params: dict | None = None


class ExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("error", mode="before")
    @classmethod
    def _redact_error(cls, v):
        return _sanitize_error(v)

    id: str
    project_id: str
    name: str
    dataset_id: str
    benchmark_id: str
    prompt_id: str
    model_id: str
    params: dict
    status: str
    metrics: dict
    total_cost: float
    total_tokens: int
    runtime_ms: int
    progress: int = 0
    rows_total: int | None = None
    accuracy: float = 0.0
    avg_latency_ms: float = 0.0
    error: str | None
    created_at: datetime
    updated_at: datetime


class ExperimentResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("error", mode="before")
    @classmethod
    def _redact_result_error(cls, v):
        return _sanitize_error(v)

    id: str
    row_idx: int
    input: dict
    expected: dict | None
    output: str
    score: float
    latency_ms: int
    tokens: int
    cost: float
    error: str | None
