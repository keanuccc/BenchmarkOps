"""Aggregates all v1 route modules into a single APIRouter.

Stage 1+ sub-agents register their routers here — this is the single wiring point,
so integration conflicts are limited to this file.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import (
    analytics,
    benchmarks,
    datasets,
    experiments,
    health,
    models,
    projects,
    prompts,
    reports,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(models.router)
api_router.include_router(datasets.router)
api_router.include_router(prompts.router)
api_router.include_router(benchmarks.router)
api_router.include_router(experiments.router)
api_router.include_router(analytics.router)
api_router.include_router(reports.router)
