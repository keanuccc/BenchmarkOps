"""FastAPI application factory for BenchmarkOps."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import acquire_writer_lock, init_db
from app.core.exceptions import register_exception_handlers
from app.middleware import get_metrics_summary, setup_structured_logging

# Configure structured logging
setup_structured_logging()

logger = logging.getLogger("benchmarkops")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[override]
    acquire_writer_lock()  # Ensure only one backend process writes to SQLite
    await init_db()
    await _log_integrity_summary()
    # Recover any experiments stuck in "running" or "queued" from a previous crash.
    await _recover_stale_experiments()
    yield


async def _log_integrity_summary() -> None:
    """Log dangling-reference counts found on startup (non-fatal)."""
    from app.core.database import AsyncSessionLocal
    from app.core.integrity import check_integrity

    try:
        async with AsyncSessionLocal() as session:
            results = await check_integrity(session)
        dangling = {
            name: count
            for name, count in results.items()
            if isinstance(count, int) and count > 0
        }
        if dangling:
            logger.warning("integrity check found issues: %s", dangling)
        else:
            logger.info("integrity check passed")
    except Exception:  # noqa: BLE001 - never block startup on a check
        logger.exception("integrity check failed")


async def _recover_stale_experiments() -> None:
    """Mark experiments stuck in 'running'/'queued' as 'failed' on startup.

    If the server crashed or was killed while an experiment was running, the
    DB will have stale status entries. This function scans for them and marks
    them as failed with a diagnostic message so the UI can show the user that
    the run did not complete successfully.

    With the ARQ backend this is intentionally skipped: the queue lives in Redis
    and workers own the run lifecycle, so a backend restart must not fail jobs
    that are still queued or being executed by a worker.
    """
    if settings.task_queue_backend == "arq":
        logger.info(
            "task_queue_backend=arq: distributed workers own run recovery; "
            "skipping stale-experiment marking"
        )
        return

    from app.core.database import AsyncSessionLocal
    from app.evaluation.task_records import mark_failed_after_restart
    from app.repositories.experiment import ExperimentRepository

    all_stale: list = []
    async with AsyncSessionLocal() as session:
        repo = ExperimentRepository(session)
        stale = await repo.list(filters={"status": "running"})
        queued = await repo.list(filters={"status": "queued"})
        all_stale = list(stale) + list(queued)
        if not all_stale:
            return
        logger.info("recovering %d stale experiment(s)", len(all_stale))
        for exp in all_stale:
            reason = (
                "Server shutdown during execution "
                f"(was {'running' if exp.status == 'running' else 'queued'})"
            )
            await repo.update(exp, {"status": "failed", "error": reason})
        await session.commit()

    # Mark task records failed on isolated sessions AFTER the experiment
    # transaction commits, so the two SQLite writers never contend.
    for exp in all_stale:
        reason = (
            "Server shutdown during execution "
            f"(was {'running' if exp.status == 'running' else 'queued'})"
        )
        await mark_failed_after_restart(exp.id, reason)


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        description="Enterprise AI Evaluation & Benchmark Operations platform.",
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/metrics")
    async def metrics() -> dict:
        """Basic application metrics endpoint (no Prometheus client needed)."""
        return get_metrics_summary()

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/")
    async def root() -> dict:
        return {"name": settings.app_name, "docs": "/docs", "api": settings.api_v1_prefix}

    return app


app = create_app()
