"""Results & Analytics API — read-only aggregation over Experiment data."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.schemas.analytics import (
    ComparisonResponse,
    FailureCase,
    LeaderboardEntry,
    ProjectAnalyticsSummary,
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
