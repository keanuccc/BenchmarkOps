"""Background dataset import: job lifecycle, idempotency, progress reporting."""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from app.core.database import AsyncSessionLocal, with_retry_on_lock
from app.core.exceptions import ConflictError, DomainError, NotFoundError, ValidationError
from app.models.import_job import ImportJob
from app.repositories.import_job import ImportJobRepository
from app.services.audit_service import record_event
from app.services.dataset_service import DatasetService

logger = logging.getLogger("benchmarkops.imports")


class ImportWorker:
    """Minimal in-process background loop for import jobs (single process)."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="import-worker"
        )
        self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def submit(self, coro_factory: Callable[[], Awaitable[None]]) -> None:
        future = asyncio.run_coroutine_threadsafe(coro_factory(), self._loop)
        future.add_done_callback(
            lambda done: done.exception() if not done.cancelled() else None
        )


import_worker = ImportWorker()


async def create_import_job(
    *,
    project_id: str,
    name: str,
    fmt: str,
    raw_bytes: bytes,
    source_filename: str | None,
    idempotency_key: str | None = None,
    mode: str = "create",
    task_type: str | None = None,
    input_fields: Any = None,
    expected_fields: Any = None,
    metadata_fields: Any = None,
    required_fields: Any = None,
    field_types: Any = None,
    answer_policy: Any = None,
    contract: Any = None,
    sensitive_fields: Any = None,
) -> ImportJob:
    """Create a queued import job (committed) or return an existing idempotent one."""
    import hashlib

    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    async with AsyncSessionLocal() as session:
        repo = ImportJobRepository(session)
        if idempotency_key:
            existing = await repo.get_by_idempotency_key(project_id, idempotency_key)
            if existing is not None:
                return existing
        job = ImportJob(
            project_id=project_id,
            name=name,
            format=fmt,
            mode=mode,
            status="queued",
            idempotency_key=idempotency_key,
            content_hash=content_hash,
            source_filename=source_filename,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

    import_worker.submit(
        lambda: _process_import_job(
            job.id,
            raw_bytes=raw_bytes,
            fmt=fmt,
            project_id=project_id,
            name=name,
            task_type=task_type,
            input_fields=input_fields,
            expected_fields=expected_fields,
            metadata_fields=metadata_fields,
            required_fields=required_fields,
            field_types=field_types,
            answer_policy=answer_policy,
            contract=contract,
            sensitive_fields=sensitive_fields,
        )
    )
    return job


async def _process_import_job(
    job_id: str,
    *,
    raw_bytes: bytes,
    fmt: str,
    project_id: str,
    name: str,
    **contract_params: Any,
) -> None:
    """Execute one import job on an isolated session; never raises."""
    try:
        async with AsyncSessionLocal() as session:
            repo = ImportJobRepository(session)
            job = await repo.get(job_id)
            if job is None:
                logger.warning("import job %s disappeared", job_id)
                return
            job.status = "running"
            await with_retry_on_lock(session.commit)

        async with AsyncSessionLocal() as session:
            service = DatasetService(session)
            dataset = await service.create_from_upload(
                project_id=project_id,
                name=name,
                description=None,
                tags=None,
                fmt=fmt,
                raw_bytes=raw_bytes,
                source_filename=job.source_filename,
                **contract_params,
            )
            await record_event(
                session,
                project_id=project_id,
                entity_type="dataset",
                entity_id=dataset.id,
                action="import",
                detail={"name": name, "format": fmt, "row_count": dataset.row_count},
            )
            await session.commit()

        await _mark_succeeded(job_id, dataset_id=dataset.id, total_rows=dataset.row_count)
    except (ValidationError, ConflictError) as exc:
        await _mark_failed(job_id, str(exc.message), getattr(exc, "details", None))
    except DomainError as exc:
        await _mark_failed(job_id, str(exc.message))
    except Exception:  # noqa: BLE001
        logger.exception("import job %s crashed", job_id)
        await _mark_failed(job_id, "Import failed (details in server logs)")


async def _mark_succeeded(job_id: str, *, dataset_id: str, total_rows: int) -> None:
    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            job = await session.get(ImportJob, job_id)
            if job is None:
                return
            job.status = "succeeded"
            job.dataset_id = dataset_id
            job.total_rows = total_rows
            job.progress = total_rows
            job.error = None
            job.error_rows = []
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()

    await with_retry_on_lock(_write)


async def _mark_failed(
    job_id: str, error: str, error_rows: list | None = None
) -> None:
    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            job = await session.get(ImportJob, job_id)
            if job is None:
                return
            job.status = "failed"
            job.error = (error or "Import failed")[:2000]
            job.error_rows = (error_rows or [])[:50]
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()

    await with_retry_on_lock(_write)


async def get_import_job(job_id: str, session) -> ImportJob:
    job = await ImportJobRepository(session).get(job_id)
    if job is None:
        raise NotFoundError(f"Import job {job_id} not found")
    return job


async def list_import_jobs(project_id: str, session) -> list[ImportJob]:
    return await ImportJobRepository(session).list_by_project(project_id)


async def recover_stale_import_jobs() -> int:
    """Mark queued/running import jobs as failed after a restart."""
    async with AsyncSessionLocal() as session:
        repo = ImportJobRepository(session)
        stale = await repo.list_stale()
        if not stale:
            return 0
        for job in stale:
            job.status = "failed"
            job.error = "Server shutdown during import"
            job.finished_at = datetime.now(timezone.utc)
        await session.commit()
        return len(stale)
