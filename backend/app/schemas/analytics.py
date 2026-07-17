"""Pydantic schemas for the Results & Analytics read-only endpoints."""
from __future__ import annotations

from pydantic import BaseModel


class LeaderboardEntry(BaseModel):
    experiment_id: str
    experiment_name: str
    model_id: str
    model_name: str
    accuracy: float
    avg_latency_ms: float
    total_cost: float
    total_tokens: int
    rows_total: int
    status: str


class ComparisonResponse(BaseModel):
    experiments: list[dict]
    dimensions: dict


class FailureCase(BaseModel):
    experiment_id: str
    row_idx: int
    input: dict
    expected: dict | None
    output: str
    score: float
    error: str | None


class TrendPoint(BaseModel):
    created_at: str
    accuracy: float
    total_cost: float
    experiment_name: str


class ProjectAnalyticsSummary(BaseModel):
    project_id: str
    experiment_count: int
    completed_count: int
    avg_accuracy: float
    total_cost: float
    total_tokens: int
    best_experiment_id: str | None
    best_accuracy: float
