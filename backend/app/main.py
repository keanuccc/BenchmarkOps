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
    # Recover any experiments stuck in "running" or "queued" from a previous crash.
    await _recover_stale_experiments()
    yield


async def _recover_stale_experiments() -> None:
    """Mark experiments stuck in 'running'/'queued' as 'failed' on startup.

    If the server crashed or was killed while an experiment was running, the
    DB will have stale status entries. This function scans for them and marks
    them as failed with a diagnostic message so the UI can show the user that
    the run did not complete successfully.
    """
    from app.core.database import AsyncSessionLocal
    from app.repositories.experiment import ExperimentRepository

    async with AsyncSessionLocal() as session:
        repo = ExperimentRepository(session)
        stale = await repo.list(filters={"status": "running"})
        queued = await repo.list(filters={"status": "queued"})
        total = len(stale) + len(queued)
        if total == 0:
            return
        logger.info("recovering %d stale experiment(s)", total)
        for exp in list(stale) + list(queued):
            await repo.update(exp, {
                "status": "failed",
                "error": f"Server shutdown during execution (was {'running' if exp.status == 'running' else 'queued'})",
            })
        await session.commit()


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
