"""Benchmark CRUD endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.security import require_auth
from app.schemas.common import ListResponse
from app.evaluation.metrics import DEFAULT_METRIC_FOR_TYPE, list_metrics
from app.schemas.benchmark import BenchmarkCreate, BenchmarkRead, BenchmarkUpdate
from app.services.benchmark_service import BenchmarkService, get_benchmark_service

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


@router.post("/", response_model=BenchmarkRead, status_code=201)
async def create_benchmark(
    data: BenchmarkCreate,
    service: BenchmarkService = Depends(get_benchmark_service),
    _: None = Depends(require_auth),
) -> BenchmarkRead:
    obj = await service.create(data)
    return BenchmarkRead.model_validate(obj)


@router.get("/", response_model=ListResponse[BenchmarkRead])
async def list_benchmarks(
    project_id: str | None = Query(default=None),
    type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: BenchmarkService = Depends(get_benchmark_service),
) -> ListResponse[BenchmarkRead]:
    objs = await service.list(
        project_id=project_id, type=type, q=q, offset=offset, limit=limit
    )
    total = await service.count(project_id=project_id, type=type, q=q)
    return ListResponse[BenchmarkRead](
        items=[BenchmarkRead.model_validate(o) for o in objs],
        total=total,
    )


@router.get("/metrics/available")
async def list_available_metrics() -> dict:
    return {"metrics": list_metrics(), "defaults": DEFAULT_METRIC_FOR_TYPE}


@router.get("/{benchmark_id}", response_model=BenchmarkRead)
async def get_benchmark(
    benchmark_id: str,
    service: BenchmarkService = Depends(get_benchmark_service),
) -> BenchmarkRead:
    obj = await service.get(benchmark_id)
    return BenchmarkRead.model_validate(obj)


@router.patch("/{benchmark_id}", response_model=BenchmarkRead)
async def update_benchmark(
    benchmark_id: str,
    data: BenchmarkUpdate,
    service: BenchmarkService = Depends(get_benchmark_service),
    _: None = Depends(require_auth),
) -> BenchmarkRead:
    obj = await service.update(benchmark_id, data)
    return BenchmarkRead.model_validate(obj)


@router.delete("/{benchmark_id}", status_code=204, response_model=None)
async def delete_benchmark(
    benchmark_id: str,
    service: BenchmarkService = Depends(get_benchmark_service),
    _: None = Depends(require_auth),
) -> None:
    await service.delete(benchmark_id)
