"""Evaluation-preparation workbench endpoints (stateless)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.security import require_auth
from app.services.prep_service import analyze_raw_data, dry_run_rows, transform_preview

router = APIRouter(prefix="/prep", tags=["prep"])

_CHUNK_SIZE = 1 << 20  # 1 MiB


async def _read_upload(file: UploadFile) -> bytes:
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
    return b"".join(parts)


@router.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    format: str | None = Form(None),
    _: None = Depends(require_auth),
) -> dict:
    """Parse a raw file and return column stats + mapping suggestions."""
    raw = await _read_upload(file)
    return analyze_raw_data(raw, filename=file.filename, fmt=format)


@router.post("/transform")
async def transform(
    file: UploadFile = File(...),
    config: str = Form(...),
    format: str | None = Form(None),
    _: None = Depends(require_auth),
) -> dict:
    """Build the platform contract + a split-row preview for a raw file."""
    try:
        config_obj = json.loads(config)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid config JSON: {exc}") from exc
    if not isinstance(config_obj, dict):
        raise ValidationError("config must be a JSON object")
    raw = await _read_upload(file)
    return transform_preview(
        raw,
        filename=file.filename,
        fmt=format,
        config=config_obj,
    )


@router.post("/dry-run")
async def dry_run(
    payload: dict,
    _: None = Depends(require_auth),
) -> dict:
    """Score a small in-memory sample without creating a dataset/experiment."""
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValidationError("payload.rows must be a list")
    if len(rows) > 500:
        raise ValidationError("dry-run supports at most 500 rows")
    return await dry_run_rows(
        rows,
        contract=payload.get("contract") or {},
        template=payload.get("template", ""),
        benchmark_type=payload.get("benchmark_type") or "qa",
        metric=payload.get("metric", ""),
        metric_config=payload.get("metric_config") or {},
        model_id=payload.get("model_id", ""),
        provider_name=payload.get("provider") or "mock",
        params=payload.get("params") or {},
        sample_size=int(payload.get("sample_size", 20) or 20),
    )
