"""Results & Analytics API — read-only aggregation over Experiment data."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.schemas.analytics import (
    ComparisonResponse,
    CompareFailuresResponse,
    FailureCase,
    LeaderboardEntry,
    ModelRoutingEntry,
    ProjectAnalyticsSummary,
    SignificanceResponse,
    SubgroupResponse,
    TrendPoint,
)
from app.core.security import require_auth
from app.services.analytics_service import (
    AnalyticsService,
    get_analytics_service,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def get_leaderboard(
    project_id: str | None = None,
    benchmark_id: str | None = None,
    limit: int = 50,
    service: AnalyticsService = Depends(get_analytics_service),
):
    return await service.leaderboard(
        project_id=project_id, benchmark_id=benchmark_id, limit=limit
    )


@router.post("/compare", response_model=ComparisonResponse)
async def compare_experiments(
    payload: dict,
    _: None = Depends(require_auth),
    service: AnalyticsService = Depends(get_analytics_service),
):
    return await service.compare(payload.get("experiment_ids", []))


@router.get(
    "/experiments/{experiment_id}/failures",
    response_model=list[FailureCase],
)
async def get_failure_cases(
    experiment_id: str,
    limit: int = 50,
    service: AnalyticsService = Depends(get_analytics_service),
):
    return await service.failure_cases(experiment_id, limit=limit)


@router.get("/trend", response_model=list[TrendPoint])
async def get_trend(
    project_id: str,
    benchmark_id: str | None = None,
    limit: int = 50,
    service: AnalyticsService = Depends(get_analytics_service),
):
    return await service.trend(project_id, benchmark_id=benchmark_id, limit=limit)


@router.get("/projects/{project_id}/summary", response_model=ProjectAnalyticsSummary)
async def get_project_summary(
    project_id: str,
    service: AnalyticsService = Depends(get_analytics_service),
):
    return await service.project_summary(project_id)


@router.get(
    "/experiments/{experiment_id}/subgroups",
    response_model=SubgroupResponse,
)
async def get_subgroups(
    experiment_id: str,
    group_field: str,
    service: AnalyticsService = Depends(get_analytics_service),
):
    return await service.subgroups(experiment_id, group_field)


@router.get(
    "/compare/failures",
    response_model=CompareFailuresResponse,
)
async def compare_failures(
    experiment_a: str,
    experiment_b: str,
    service: AnalyticsService = Depends(get_analytics_service),
):
    return await service.compare_failures(experiment_a, experiment_b)


@router.get("/model-routing", response_model=list[ModelRoutingEntry])
async def get_model_routing(
    project_id: str,
    min_accuracy: float = 0.8,
    limit: int = 10,
    service: AnalyticsService = Depends(get_analytics_service),
):
    return await service.model_routing(
        project_id, min_accuracy=min_accuracy, limit=limit
    )


@router.get("/significance", response_model=SignificanceResponse)
async def get_significance(
    experiment_a: str,
    experiment_b: str,
    n_iterations: int = 2000,
    confidence: float = 0.95,
    seed: int | None = None,
    service: AnalyticsService = Depends(get_analytics_service),
):
    return await service.significance(
        experiment_a,
        experiment_b,
        n_iterations=n_iterations,
        confidence=confidence,
        seed=seed,
    )
