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
    dataset_rows_total: int
    coverage: float
    failure_rate: float
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
    coverage: float = 0.0
    failure_rate: float = 0.0


class ProjectAnalyticsSummary(BaseModel):
    project_id: str
    experiment_count: int
    completed_count: int
    avg_accuracy: float
    total_cost: float
    total_tokens: int
    best_experiment_id: str | None
    best_accuracy: float
    coverage: float
    failure_rate: float


class SubgroupEntry(BaseModel):
    group: str
    row_count: int
    avg_score: float
    pass_count: int
    fail_count: int
    error_count: int


class SubgroupResponse(BaseModel):
    experiment_id: str
    group_field: str
    total_rows: int
    groups: list[SubgroupEntry]


class CompareFailureCase(BaseModel):
    row_idx: int
    input: dict
    expected: dict | None
    a_output: str
    a_score: float
    b_output: str
    b_score: float


class CompareFailuresResponse(BaseModel):
    experiment_a: str
    experiment_b: str
    a_only_wrong: list[CompareFailureCase]
    b_only_wrong: list[CompareFailureCase]
    both_wrong: list[CompareFailureCase]


class ModelRoutingEntry(BaseModel):
    model_id: str
    model_name: str
    experiment_id: str
    accuracy: float
    avg_latency_ms: float
    total_cost: float
    total_tokens: int
    recommended: bool = False


class BootstrapCISummary(BaseModel):
    mean: float
    lower: float
    upper: float
    n: int


class SignificanceResponse(BaseModel):
    experiment_a: str
    experiment_b: str
    paired_rows: int
    a: BootstrapCISummary
    b: BootstrapCISummary
    mean_diff: float
    diff_ci_lower: float
    diff_ci_upper: float
    p_value: float
    significant: bool
    mcnemar_p_value: float
    mcnemar_significant: bool
