"""Experiment API — CRUD + Evaluation Engine controls (run/retry/duplicate)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.core.exceptions import ConflictError
from app.core.security import require_auth
from app.evaluation.task_queue import task_queue
from app.schemas.experiment import (
    ExperimentCreate,
    ExperimentRecomputeReport,
    ExperimentRead,
    ExperimentResultRead,
    ExperimentUpdate,
)
from app.services.experiment_service import (
    ExperimentService,
    get_experiment_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments", tags=["experiments"])


class DuplicateRequest(BaseModel):
    name: str | None = None


@router.post("/", response_model=ExperimentRead, status_code=status.HTTP_201_CREATED)
async def create_experiment(
    payload: ExperimentCreate,
    service: ExperimentService = Depends(get_experiment_service),
    _: None = Depends(require_auth),
):
    return await service.create(payload)


@router.get("/", response_model=list[ExperimentRead])
async def list_experiments(
    project_id: str | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 100,
    service: ExperimentService = Depends(get_experiment_service),
):
    return await service.list(
        project_id=project_id, status=status, offset=offset, limit=limit
    )


@router.get("/{experiment_id}", response_model=ExperimentRead)
async def get_experiment(
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
):
    return await service.get(experiment_id)


@router.get("/{experiment_id}/results", response_model=list[ExperimentResultRead])
async def get_results(
    experiment_id: str,
    offset: int = 0,
    limit: int = 1000,
    service: ExperimentService = Depends(get_experiment_service),
):
    return await service.list_results(experiment_id, offset=offset, limit=limit)


@router.post("/{experiment_id}/recompute-scores", response_model=ExperimentRecomputeReport)
async def recompute_scores(
    experiment_id: str,
    diff_limit: int = 100,
    service: ExperimentService = Depends(get_experiment_service),
    _: None = Depends(require_auth),
):
    return await service.recompute_scores(experiment_id, diff_limit=diff_limit)


@router.patch("/{experiment_id}", response_model=ExperimentRead)
async def update_experiment(
    experiment_id: str,
    payload: ExperimentUpdate,
    service: ExperimentService = Depends(get_experiment_service),
    _: None = Depends(require_auth),
):
    return await service.update(experiment_id, payload)


@router.post("/{experiment_id}/run", response_model=ExperimentRead)
async def run_experiment_endpoint(
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
    _: None = Depends(require_auth),
):
    logger.info("experiment %s run submitted", experiment_id)
    return await service.run(experiment_id)


@router.post("/{experiment_id}/retry", response_model=ExperimentRead)
async def retry_experiment(
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
    _: None = Depends(require_auth),
):
    logger.info("experiment %s retry submitted", experiment_id)
    return await service.retry(experiment_id)


@router.post(
    "/{experiment_id}/duplicate",
    response_model=ExperimentRead,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_experiment(
    experiment_id: str,
    payload: DuplicateRequest,
    service: ExperimentService = Depends(get_experiment_service),
    _: None = Depends(require_auth),
):
    return await service.duplicate(experiment_id, payload.name)


@router.delete("/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_experiment(
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
    _: None = Depends(require_auth),
):
    await service.delete(experiment_id)


@router.post("/{experiment_id}/cancel", response_model=ExperimentRead)
async def cancel_experiment(
    experiment_id: str,
    service: ExperimentService = Depends(get_experiment_service),
    _: None = Depends(require_auth),
) -> ExperimentRead:
    """Cancel a running experiment. The runner will stop after the current row."""
    exp = await service.get(experiment_id)
    if exp.status not in ("running", "queued"):
        raise ConflictError(f"Cannot cancel experiment with status '{exp.status}'")
    # Signal cancellation at the DB level (runner checks this between rows)
    from app.core.database import AsyncSessionLocal
    from app.repositories.experiment import ExperimentRepository

    async with AsyncSessionLocal() as session:
        repo = ExperimentRepository(session)
        await repo.update(exp, {"status": "cancelled"})
        await session.commit()
    # Also signal the background task to cancel immediately
    task_queue.cancel_task(experiment_id)
    return await service.get(experiment_id)


class RunningTaskInfo(BaseModel):
    """Info about a currently running background task."""
    experiment_id: str
    name: str | None = None
    project_id: str | None = None


@router.get("/running", response_model=list[RunningTaskInfo])
async def get_running_tasks(
    service: ExperimentService = Depends(get_experiment_service),
) -> list[RunningTaskInfo]:
    """List experiments that are currently being evaluated (status=running)."""
    running_exps = await service.list(status="running")
    return [
        RunningTaskInfo(
            experiment_id=e.id,
            name=e.name,
            project_id=e.project_id,
        )
        for e in running_exps
    ]
