"""Dataset Center API routes."""
from __future__ import annotations

from typing import Sequence

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.exceptions import ValidationError
from app.core.security import require_auth
from app.schemas.dataset import DatasetRead, DatasetRowRead, DatasetUpdate
from app.services.dataset_parser import parse_dataset
from app.services.dataset_service import DatasetService, get_dataset_service

router = APIRouter(prefix="/datasets", tags=["datasets"])

_CHUNK_SIZE = 1 << 20  # 1 MiB; never hold the whole file in memory at once


@router.post("/upload", response_model=DatasetRead)
async def upload_dataset(
    project_id: str = Form(...),
    name: str = Form(...),
    description: str | None = Form(None),
    tags: str | None = Form(None),
    format: str | None = Form(None),
    file: UploadFile = File(...),
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> Dataset:
    # Chunked read with an absolute byte cap — reject oversized uploads before
    # they can OOM the process (was: `raw = await file.read()`, no limit).
    total = 0
    parts: list[bytes] = []
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_upload_bytes:
            raise ValidationError(
                f"Upload too large: {total} bytes exceeds limit "
                f"of {settings.max_upload_bytes} bytes"
            )
        parts.append(chunk)
    raw = b"".join(parts)

    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    fmt = format
    if not fmt and file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        fmt = {"jsonl": "jsonl", "json": "json", "csv": "csv"}.get(ext, "json")
    fmt = fmt or "json"

    # Parse once here only to enforce the row cap (entry guard for the runner's
    # full-fetch downstream). The service re-parses identically — behavior
    # elsewhere is unchanged.
    row_count = len(parse_dataset(raw, fmt))
    if row_count > settings.max_dataset_rows:
        raise ValidationError(
            f"Dataset too large: {row_count} rows exceeds limit "
            f"of {settings.max_dataset_rows} rows"
        )

    return await service.create_from_upload(
        project_id=project_id,
        name=name,
        description=description,
        tags=tag_list,
        fmt=fmt,
        raw_bytes=raw,
    )


@router.get("/", response_model=list[DatasetRead])
async def list_datasets(
    project_id: str | None = Query(None),
    offset: int = Query(0),
    limit: int = Query(100),
    service: DatasetService = Depends(get_dataset_service),
) -> Sequence[Dataset]:
    return await service.list(project_id=project_id, offset=offset, limit=limit)


@router.get("/{dataset_id}", response_model=DatasetRead)
async def get_dataset(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
) -> Dataset:
    return await service.get(dataset_id)


@router.get("/{dataset_id}/preview", response_model=list[DatasetRowRead])
async def preview_dataset(
    dataset_id: str,
    offset: int = Query(0),
    limit: int = Query(20),
    service: DatasetService = Depends(get_dataset_service),
) -> Sequence[DatasetRow]:
    return await service.preview(dataset_id, offset=offset, limit=limit)


@router.get("/{dataset_id}/stats", response_model=dict)
async def dataset_stats(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
) -> dict:
    return await service.get_stats(dataset_id)


@router.post("/{dataset_id}/validate", response_model=dict)
async def validate_dataset(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> dict:
    return await service.validate(dataset_id)


@router.patch("/{dataset_id}", response_model=DatasetRead)
async def update_dataset(
    dataset_id: str,
    data: DatasetUpdate,
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> Dataset:
    return await service.update(dataset_id, data)


@router.delete("/{dataset_id}", status_code=204, response_model=None)
async def delete_dataset(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> None:
    await service.delete(dataset_id)
