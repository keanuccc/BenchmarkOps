"""Pydantic v2 DTOs for the Experiment module."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Error strings persisted in DB are internal diagnostics (raw exception text) and may
# contain SQL, filesystem paths, or other sensitive detail. Redact them before they
# reach clients: keep only the exception type and a short, detail-free summary.
#
# A small allowlist of operational keywords is passed through verbatim so the UI can
# tell the user *what* went wrong (locked DB, rate limited, provider down) without
# leaking SQL/stack/full paths. Anything else is reduced to a generic type tag.
_ALLOWED_KEYWORDS = (
    "database is locked",
    "rate limited",
    "ProviderRateLimitedError",
    "timeout",
    "OperationalError",
    "ConnectionError",
)


def _sanitize_error(value: str | None) -> str | None:
    if not value:
        return value
    lowered = value.lower()
    # Match the most specific keyword first so e.g. "ProviderRateLimitedError"
    # wins over the shorter "rate limited" substring it also contains.
    for kw in sorted(_ALLOWED_KEYWORDS, key=len, reverse=True):
        if kw.lower() in lowered:
            # Preserve the keyword and a short, detail-free tail of the original.
            return f"{kw} (details in server logs)"[:80]
    # First line is the message; the head (before ":") is usually the exception type.
    first_line = value.splitlines()[0] if value.splitlines() else value
    etype = first_line.split(":", 1)[0].strip()
    safe = etype if etype and etype != first_line.strip() else "evaluation_error"
    return f"{safe} (details in server logs)"[:80]


class ExperimentCreate(BaseModel):
    project_id: str
    name: str
    dataset_id: str
    dataset_version: int | None = None
    benchmark_id: str
    prompt_id: str
    model_id: str  # DB id of a Model row
    params: dict = Field(default_factory=dict)


class ExperimentBatchCreate(BaseModel):
    project_id: str
    name: str | None = None
    dataset_id: str
    dataset_version: int | None = None
    benchmark_id: str
    prompt_id: str
    model_ids: list[str]
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
    dataset_version: int | None = None
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
    cells_done: int = 0
    cells_error: int = 0
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
    cleaned_prediction: str | None = None
    expected_canonical: str | None = None
    score_reason: str | None = None
    latency_ms: int
    tokens: int
    cost: float
    error: str | None


class ExperimentRecomputeDifference(BaseModel):
    row_idx: int
    stored_score: float
    recomputed_score: float
    cleaned_prediction: str
    expected_canonical: str
    score_reason: str


class ExperimentRecomputeReport(BaseModel):
    metric: str
    rows_total: int
    dataset_rows_total: int
    rows_scored: int
    rows_failed: int
    rows_unprocessed: int
    coverage: float
    failure_rate: float
    stored_accuracy: float
    recomputed_accuracy: float
    changed_rows: int
    differences: list[ExperimentRecomputeDifference]
