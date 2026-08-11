"""Experiment API — CRUD + Evaluation Engine controls (run/retry/duplicate)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.core.exceptions import ConflictError
from app.core.security import require_auth
from app.evaluation.cancellation import request_cancel
from app.evaluation.task_records import mark_done
from app.evaluation.task_queue import task_queue
from app.schemas.common import ListResponse
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
from app.services.redaction import redact_text, redact_values

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments", tags=["experiments"])


class DuplicateRequest(BaseModel):
    name: str | None = None


class RunningTaskInfo(BaseModel):
    """Info about a queued or currently running background task."""
    experiment_id: str
    name: str | None = None
    project_id: str | None = None
    status: str = "running"


@router.get("/running", response_model=list[RunningTaskInfo])
async def get_running_tasks(
    service: ExperimentService = Depends(get_experiment_service),
) -> list[RunningTaskInfo]:
    """List experiments that are queued or currently being evaluated.

    Registered before ``/{experiment_id}`` so the literal ``running`` segment
    is never swallowed by the dynamic id route.
    """
    running_exps = await service.list(status="running")
    queued_exps = await service.list(status="queued")
    return [
        RunningTaskInfo(
            experiment_id=e.id,
            name=e.name,
            project_id=e.project_id,
            status=e.status,
        )
        for e in [*running_exps, *queued_exps]
    ]


@router.post("/", response_model=ExperimentRead, status_code=status.HTTP_201_CREATED)
async def create_experiment(
    payload: ExperimentCreate,
    service: ExperimentService = Depends(get_experiment_service),
    _: None = Depends(require_auth),
):
    return await service.create(payload)


@router.get("/", response_model=ListResponse[ExperimentRead])
async def list_experiments(
    project_id: str | None = None,
    status: str | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = 100,
    service: ExperimentService = Depends(get_experiment_service),
):
    items = await service.list(
        project_id=project_id, status=status, q=q, offset=offset, limit=limit
    )
    total = await service.count(project_id=project_id, status=status, q=q)
    return ListResponse[ExperimentRead](items=items, total=total)


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
    mask_sensitive: bool = Query(False),
    service: ExperimentService = Depends(get_experiment_service),
):
    results = await service.list_results(experiment_id, offset=offset, limit=limit)
    if not mask_sensitive:
        return results
    sensitive = await service.get_sensitive_fields(experiment_id)
    masked = []
    for result in results:
        read = ExperimentResultRead.model_validate(result)
        read.input = redact_values(read.input, sensitive)
        if read.expected is not None:
            read.expected = redact_values(read.expected, sensitive)
        read.output = redact_text(read.output or "")
        masked.append(read)
    return masked


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
        fresh = await repo.get(experiment_id)
        if fresh is None:
            raise ConflictError("Experiment no longer exists")
        if fresh.status not in ("running", "queued"):
            raise ConflictError(f"Cannot cancel experiment with status '{fresh.status}'")
        await repo.update(fresh, {"status": "cancelled"})
        await session.commit()
    await mark_done(experiment_id, status="cancelled")
    # Also signal the background task to stop at the next row boundary
    request_cancel(experiment_id)
    task_queue.cancel_task(experiment_id)
    return await service.get(experiment_id)


