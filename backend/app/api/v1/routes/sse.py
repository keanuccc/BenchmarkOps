"""Server-Sent Events stream for experiment progress updates."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.database import AsyncSessionLocal
from app.repositories.experiment import ExperimentRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments", tags=["sse"])

ACTIVE_STATUSES = {"running", "pending", "queued"}


@router.get("/{experiment_id}/stream")
async def experiment_stream(experiment_id: str):
    """SSE endpoint for real-time experiment progress updates."""
    return StreamingResponse(
        _event_generator(experiment_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


async def _event_generator(experiment_id: str):
    """Async generator that yields SSE events for an experiment."""
    last_status: str | None = None
    last_progress: float = -1.0
    last_metrics: dict = {}
    last_updated: str | None = None
    event_id = 0

    while True:
        try:
            async with AsyncSessionLocal() as session:
                repo = ExperimentRepository(session)
                exp = await repo.get(experiment_id)
                if exp is None:
                    yield f"id: {event_id}\nevent: error\ndata: {{\"error\":\"experiment not found\"}}\n\n"
                    return

                current_status = exp.status
                current_progress = float(exp.progress or 0)
                current_metrics = exp.metrics or {}
                current_updated = exp.updated_at

                # Only emit when something changed
                changed = (
                    current_status != last_status
                    or abs(current_progress - last_progress) > 0.5
                    or current_metrics != last_metrics
                    or current_updated != last_updated
                )

                if changed:
                    event_id += 1
                    data = {
                        "id": exp.id,
                        "status": current_status,
                        "progress": current_progress,
                        "rows_total": exp.rows_total,
                        "cells_done": exp.cells_done,
                        "cells_error": exp.cells_error,
                        "accuracy": exp.accuracy,
                        "metrics": current_metrics,
                        "total_cost": exp.total_cost,
                        "total_tokens": exp.total_tokens,
                        "runtime_ms": exp.runtime_ms,
                        "updated_at": current_updated,
                    }
                    yield f"id: {event_id}\nevent: progress\ndata: {json.dumps(data)}\n\n"

                    last_status = current_status
                    last_progress = current_progress
                    last_metrics = current_metrics
                    last_updated = current_updated

                # Terminal states — stop streaming
                if current_status not in ACTIVE_STATUSES:
                    logger.info("experiment %s reached terminal state %s, stopping SSE", experiment_id, current_status)
                    return

        except Exception:  # noqa: BLE001
            logger.exception("SSE stream error for experiment %s", experiment_id)
            yield f"id: {event_id}\nevent: error\ndata: {{\"error\":\"stream error\"}}\n\n"
            return

        # Poll every 500ms — much less aggressive than the old 1s polling
        await asyncio.sleep(0.5)
