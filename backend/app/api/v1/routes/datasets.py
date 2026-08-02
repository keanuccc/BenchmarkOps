"""Dataset Center API routes."""
from __future__ import annotations

from typing import Sequence

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.security import require_auth
from app.schemas.common import ListResponse
from app.models.audit import AuditEvent
from app.models.dataset import Dataset, DatasetRow, DatasetVersion
from app.schemas.dataset import (
    AuditEventRead,
    DatasetRead,
    DatasetRowRead,
    DatasetUpdate,
    DatasetVersionRead,
    ImportJobRead,
)
from app.services.dataset_parser import infer_format, parse_dataset
from app.services.dataset_service import DatasetService, get_dataset_service
from app.services.audit_service import list_events as list_audit_events
from app.services.import_service import (
    create_import_job as start_import_job,
    get_import_job as fetch_import_job,
    list_import_jobs as fetch_import_jobs,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])

_CHUNK_SIZE = 1 << 20  # 1 MiB; never hold the whole file in memory at once


def _sensitive_fields(dataset: Dataset) -> set[str]:
    return set((dataset.contract or {}).get("sensitive_fields", []) or [])


def _redact(value: dict, sensitive: set[str]) -> dict:
    """Mask declared sensitive fields (top-level and inside _metadata)."""
    out: dict = {}
    for key, item in value.items():
        if key in sensitive:
            out[key] = "[REDACTED]"
        elif key == "_metadata" and isinstance(item, dict):
            out[key] = {
                k: ("[REDACTED]" if k in sensitive else v) for k, v in item.items()
            }
        else:
            out[key] = item
    return out


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
    sensitive_fields: str | None = Form(None),
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
    fmt = infer_format(file.filename, format)

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
        sensitive_fields=sensitive_fields,
        source_filename=file.filename,
    )


@router.post("/import", response_model=ImportJobRead, status_code=202)
async def import_dataset(
    project_id: str = Form(...),
    name: str = Form(...),
    format: str | None = Form(None),
    idempotency_key: str | None = Form(None),
    task_type: str | None = Form(None),
    input_fields: str | None = Form(None),
    expected_fields: str | None = Form(None),
    metadata_fields: str | None = Form(None),
    required_fields: str | None = Form(None),
    field_types: str | None = Form(None),
    answer_policy: str | None = Form(None),
    contract: str | None = Form(None),
    sensitive_fields: str | None = Form(None),
    file: UploadFile = File(...),
    _: None = Depends(require_auth),
) -> ImportJobRead:
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

    fmt = infer_format(file.filename, format)

    row_count = len(parse_dataset(raw, fmt))
    if row_count > settings.max_dataset_rows:
        raise ValidationError(
            f"Dataset too large: {row_count} rows exceeds limit "
            f"of {settings.max_dataset_rows} rows"
        )

    return await start_import_job(
        project_id=project_id,
        name=name,
        fmt=fmt,
        raw_bytes=raw,
        source_filename=file.filename,
        idempotency_key=idempotency_key,
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


@router.get("/imports", response_model=ListResponse[ImportJobRead])
async def list_imports(
    project_id: str = Query(...),
    service: DatasetService = Depends(get_dataset_service),
) -> ListResponse[ImportJobRead]:
    items = await fetch_import_jobs(project_id, service.session)
    return ListResponse[ImportJobRead](items=items, total=len(items))


@router.get("/imports/{job_id}", response_model=ImportJobRead)
async def get_import(
    job_id: str,
    service: DatasetService = Depends(get_dataset_service),
) -> ImportJobRead:
    return await fetch_import_job(job_id, service.session)


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
    version: int | None = Query(None),
) -> dict:
    """Return first 10 rows + metadata from an uploaded dataset."""
    dataset = await service.get(dataset_id)
    sensitive = _sensitive_fields(dataset)
    rows = await service.preview(dataset_id, offset=0, limit=10, version=version)
    columns: list[str] = dataset.column_schema or []
    total_rows = dataset.row_count
    if version is not None:
        meta = next(
            (v for v in await service.list_versions(dataset_id) if v.version == version),
            None,
        )
        if meta is not None:
            total_rows = meta.row_count
            sensitive = set((meta.contract or {}).get("sensitive_fields", []) or [])
    return {
        "rows": [
            {
                k: str(v)
                for k, v in _redact(
                    {**r.input, **(r.expected or {})}, sensitive
                ).items()
            }
            for r in rows
        ],
        "total_rows": total_rows,
        "columns": columns,
        "sample_count": len(rows),
    }


@router.post("/{dataset_id}/validate/quick", response_model=dict)
async def validate_dataset_quick(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
    version: int | None = Query(None),
    _: None = Depends(require_auth),
) -> dict:
    """Lightweight validation — parseability, required fields, empty rows."""
    dataset = await service.get(dataset_id)
    errors: list[str] = []
    warnings: list[str] = []
    effective_version = dataset.version if version is None else version
    meta = None
    if version is not None:
        meta = next(
            (v for v in await service.list_versions(dataset_id) if v.version == version),
            None,
        )
    if meta is not None:
        contract = meta.contract or {}
        import_status = meta.import_status
        import_errors = meta.import_errors or []
    else:
        contract = dataset.contract or {}
        import_status = dataset.import_status
        import_errors = dataset.import_errors or []

    # 1. File is parseable (already parsed at upload time; check import_errors)
    if import_status != "ready":
        errors.extend(import_errors or ["Dataset import failed"])

    # 2. Required fields present (input-like + expected-like)
    mapping = contract.get("field_mapping", dataset.field_mapping or {}) or {}
    input_fields = mapping.get("input_fields") or []
    expected_fields = mapping.get("expected_fields") or []
    if not input_fields:
        warnings.append("No input fields defined; all columns will be used as input")
    if not expected_fields:
        warnings.append("No expected fields defined; answers may not be scored correctly")

    # 3. No empty required rows
    rows = await service.preview(
        dataset_id, offset=0, limit=1_000_000, version=effective_version
    )
    required_fields = contract.get("required_fields", []) or []
    for row in rows:
        all_vals = {**row.input}
        if row.expected:
            all_vals.update(row.expected)
        for field in required_fields:
            value = all_vals.get(field)
            if field in all_vals and (
                value in (None, "", {})
                or (isinstance(value, str) and not value.strip())
            ):
                errors.append(f"Row {row.idx}: required field '{field}' is empty")
        if not any(
            v not in (None, "", {})
            and not (isinstance(v, str) and not v.strip())
            for v in all_vals.values()
        ):
            errors.append(f"Row {row.idx}: all fields are empty")

    valid = len(errors) == 0
    return {"valid": valid, "errors": errors, "warnings": warnings}


@router.get("/{dataset_id}/preview", response_model=list[DatasetRowRead])
async def preview_dataset(
    dataset_id: str,
    offset: int = Query(0),
    limit: int = Query(20),
    version: int | None = Query(None),
    service: DatasetService = Depends(get_dataset_service),
) -> Sequence[DatasetRow]:
    dataset = await service.get(dataset_id)
    sensitive = _sensitive_fields(dataset)
    if version is not None:
        meta = next(
            (v for v in await service.list_versions(dataset_id) if v.version == version),
            None,
        )
        if meta is not None:
            sensitive = set((meta.contract or {}).get("sensitive_fields", []) or [])
    rows = await service.preview(dataset_id, offset=offset, limit=limit, version=version)
    return [
        DatasetRowRead(
            id=row.id,
            idx=row.idx,
            input=_redact(row.input, sensitive),
            expected=_redact(row.expected, sensitive) if row.expected else None,
        )
        for row in rows
    ]


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
    version: int | None = Query(None),
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> dict:
    variables = (
        [v.strip() for v in prompt_variables.split(",") if v.strip()]
        if prompt_variables
        else None
    )
    return await service.validate(
        dataset_id, prompt_variables=variables, version=version
    )


@router.post("/{dataset_id}/versions", response_model=DatasetVersionRead)
async def upload_dataset_version(
    dataset_id: str,
    file: UploadFile = File(...),
    mode: str = Form("replace"),
    format: str | None = Form(None),
    task_type: str | None = Form(None),
    input_fields: str | None = Form(None),
    expected_fields: str | None = Form(None),
    metadata_fields: str | None = Form(None),
    required_fields: str | None = Form(None),
    field_types: str | None = Form(None),
    answer_policy: str | None = Form(None),
    contract: str | None = Form(None),
    sensitive_fields: str | None = Form(None),
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> DatasetVersion:
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

    fmt = infer_format(file.filename, format)

    row_count = len(parse_dataset(raw, fmt))
    if row_count > settings.max_dataset_rows:
        raise ValidationError(
            f"Dataset too large: {row_count} rows exceeds limit "
            f"of {settings.max_dataset_rows} rows"
        )

    return await service.create_version(
        dataset_id,
        raw,
        fmt,
        mode=mode,
        task_type=task_type,
        input_fields=input_fields,
        expected_fields=expected_fields,
        metadata_fields=metadata_fields,
        required_fields=required_fields,
        field_types=field_types,
        answer_policy=answer_policy,
        contract=contract,
        sensitive_fields=sensitive_fields,
        source_filename=file.filename,
    )


@router.get("/{dataset_id}/versions", response_model=list[DatasetVersionRead])
async def list_dataset_versions(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
) -> Sequence[DatasetVersion]:
    return await service.list_versions(dataset_id)


@router.post(
    "/{dataset_id}/versions/{version}/activate", response_model=DatasetRead
)
async def activate_dataset_version(
    dataset_id: str,
    version: int,
    service: DatasetService = Depends(get_dataset_service),
    _: None = Depends(require_auth),
) -> Dataset:
    return await service.activate_version(dataset_id, version)


@router.get("/{dataset_id}/audit", response_model=list[AuditEventRead])
async def dataset_audit(
    dataset_id: str,
    service: DatasetService = Depends(get_dataset_service),
) -> Sequence[AuditEvent]:
    await service.get(dataset_id)
    return await list_audit_events(
        service.session, entity_type="dataset", entity_id=dataset_id
    )


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
