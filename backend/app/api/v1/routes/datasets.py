"""Dataset Center API routes."""
from __future__ import annotations

from typing import Sequence

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.security import require_auth
from app.schemas.common import ListResponse
from app.models.dataset import Dataset, DatasetRow
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
    task_type: str | None = Form(None),
    input_fields: str | None = Form(None),
    expected_fields: str | None = Form(None),
    metadata_fields: str | None = Form(None),
    required_fields: str | None = Form(None),
    field_types: str | None = Form(None),
    answer_policy: str | None = Form(None),
    contract: str | None = Form(None),
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
        task_type=task_type,
        input_fields=input_fields,
        expected_fields=expected_fields,
        metadata_fields=metadata_fields,
        required_fields=required_fields,
        field_types=field_types,
        answer_policy=answer_policy,
        contract=contract,
        source_filename=file.filename,
    )


@router.get("/", response_model=ListResponse[DatasetRead])
async def list_datasets(
    project_id: str | None = Query(None),
    q: str | None = Query(None),
    offset: int = Query(0),
    limit: int = Query(100),
    service: DatasetService = Depends(get_dataset_service),
) -> ListResponse[DatasetRead]:
    items = await service.list(project_id=project_id, q=q, offset=offset, limit=limit)
    total = await service.count(project_id=project_id, q=q)
    return ListResponse[DatasetRead](items=items, total=total)


@router.get("/{dataset_id}", response_model=DatasetRead)
async def get_dataset(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
) -> Dataset:
    return await service.get(dataset_id)


@router.get("/{dataset_id}/preview/raw", response_model=dict)
async def preview_dataset_raw(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
) -> dict:
    """Return first 10 rows + metadata from an uploaded dataset."""
    dataset = await service.get(dataset_id)
    rows = await service.preview(dataset_id, offset=0, limit=10)
    columns: list[str] = dataset.column_schema or []
    return {
        "rows": [
            {k: str(v) for k, v in {**r.input, **(r.expected or {})}.items()}
            for r in rows
        ],
        "total_rows": dataset.row_count,
        "columns": columns,
        "sample_count": len(rows),
    }


@router.post("/{dataset_id}/validate/quick", response_model=dict)
async def validate_dataset_quick(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> dict:
    """Lightweight validation — parseability, required fields, empty rows."""
    dataset = await service.get(dataset_id)
    errors: list[str] = []
    warnings: list[str] = []

    # 1. File is parseable (already parsed at upload time; check import_errors)
    if dataset.import_status != "ready":
        errors.extend(dataset.import_errors or ["Dataset import failed"])

    # 2. Required fields present (input-like + expected-like)
    mapping = (dataset.contract or {}).get("field_mapping", dataset.field_mapping or {}) or {}
    input_fields = mapping.get("input_fields") or []
    expected_fields = mapping.get("expected_fields") or []
    if not input_fields:
        warnings.append("No input fields defined; all columns will be used as input")
    if not expected_fields:
        warnings.append("No expected fields defined; answers may not be scored correctly")

    # 3. No empty required rows
    rows = await service.preview(dataset_id, offset=0, limit=dataset.row_count)
    contract = dataset.contract or {}
    required_fields = contract.get("required_fields", []) or []
    for row in rows:
        all_vals = {**row.input}
        if row.expected:
            all_vals.update(row.expected)
        for field in required_fields:
            if field in all_vals and all_vals[field] in (None, "", {}):
                errors.append(f"Row {row.idx}: required field '{field}' is empty")
        if not any(v for v in all_vals.values() if v not in (None, "", {})):
            errors.append(f"Row {row.idx}: all fields are empty")

    valid = len(errors) == 0
    return {"valid": valid, "errors": errors, "warnings": warnings}


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
    prompt_variables: str | None = Query(None),
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> dict:
    variables = (
        [v.strip() for v in prompt_variables.split(",") if v.strip()]
        if prompt_variables
        else None
    )
    return await service.validate(dataset_id, prompt_variables=variables)


@router.patch("/{dataset_id}", response_model=DatasetRead)
async def update_dataset(
    dataset_id: str,
    data: DatasetUpdate,
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> Dataset:
    return await service.update(dataset_id, data)


@router.post("/{dataset_id}/archive", response_model=DatasetRead)
async def archive_dataset(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> Dataset:
    return await service.archive(dataset_id)


@router.post("/{dataset_id}/unarchive", response_model=DatasetRead)
async def unarchive_dataset(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> Dataset:
    return await service.unarchive(dataset_id)


@router.delete("/{dataset_id}", status_code=204, response_model=None)
async def delete_dataset(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> None:
    await service.delete(dataset_id)
