"""Pure parsing helpers for dataset import (no DB access)."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.core.exceptions import ValidationError

_EXPECTED_KEYS = ("expected", "answer", "label", "output", "target", "ground_truth")
_SUPPORTED = ("csv", "json", "jsonl")


def _decode_bytes(raw_bytes: bytes) -> str:
    """Decode raw file bytes to text, trying UTF-8 first then falling back to GBK."""
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        # Fallback for Windows-exported CSVs (GBK/GB2312 encoding).
        return raw_bytes.decode("gbk")


def parse_dataset(raw_bytes: bytes, fmt: str) -> list[dict]:
    fmt = (fmt or "").strip().lower()
    if fmt not in _SUPPORTED:
        raise ValidationError(f"Unsupported format: {fmt!r}")

    text = _decode_bytes(raw_bytes)
    rows: list[dict]

    if fmt == "csv":
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValidationError("CSV has no header row")
        rows = [dict(r) for r in reader]
    elif fmt == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Invalid JSON: {exc}") from exc
        if isinstance(data, dict):
            for key in ("data", "rows"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ValidationError("JSON must be a list of objects")
        rows = data
    else:  # jsonl
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValidationError(f"Invalid JSONL line: {exc}") from exc

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValidationError(f"Row {i} is not a JSON object")
    return rows


def infer_schema(rows: list[dict]) -> list[str]:
    schema: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in schema:
                schema.append(key)
    return schema


def compute_stats(rows: list[dict]) -> dict:
    columns = infer_schema(rows)
    null_counts = {col: 0 for col in columns}
    for row in rows:
        for col in columns:
            if col not in row or row[col] in (None, ""):
                null_counts[col] += 1
    return {
        "row_count": len(rows),
        "column_count": len(columns),
        "columns": columns,
        "null_counts": null_counts,
    }


def _field_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"Invalid field list JSON: {exc}") from exc
        else:
            return [part.strip() for part in text.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValidationError("Field lists must be arrays or comma-separated strings")


def _json_object(value: Any, label: str) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Invalid {label} JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value


def build_dataset_contract(
    rows: list[dict],
    *,
    task_type: str | None = None,
    input_fields: Any = None,
    expected_fields: Any = None,
    metadata_fields: Any = None,
    required_fields: Any = None,
    field_types: Any = None,
    answer_policy: Any = None,
    contract: Any = None,
) -> dict:
    """Build a lightweight dataset contract for import and validation."""
    payload = _json_object(contract, "contract")
    columns = infer_schema(rows)
    nested_mapping = payload.get("field_mapping")
    if not isinstance(nested_mapping, dict):
        nested_mapping = {}

    mapped_input = _field_list(
        input_fields
        if input_fields is not None
        else payload.get("input_fields", nested_mapping.get("input_fields"))
    )
    mapped_expected = _field_list(
        expected_fields
        if expected_fields is not None
        else payload.get("expected_fields", nested_mapping.get("expected_fields"))
    )
    mapped_metadata = _field_list(
        metadata_fields
        if metadata_fields is not None
        else payload.get("metadata_fields", nested_mapping.get("metadata_fields"))
    )

    if not mapped_expected:
        mapped_expected = [col for col in columns if col in _EXPECTED_KEYS]
    if not mapped_input:
        excluded = set(mapped_expected) | set(mapped_metadata)
        mapped_input = [col for col in columns if col not in excluded]

    roles = {
        "input": set(mapped_input),
        "expected": set(mapped_expected),
        "metadata": set(mapped_metadata),
    }
    overlap = (
        (roles["input"] & roles["expected"])
        | (roles["input"] & roles["metadata"])
        | (roles["expected"] & roles["metadata"])
    )
    if overlap:
        field = sorted(overlap)[0]
        raise ValidationError(f"Field mapped to multiple roles: {field}")

    for field in mapped_expected:
        if field not in columns and not any(_source_has_field(row, field) for row in rows):
            raise ValidationError(f"Expected field '{field}' is not present in source")

    try:
        schema_version = int(payload.get("schema_version", 1) or 1)
    except (TypeError, ValueError) as exc:
        raise ValidationError("schema_version must be an integer") from exc

    normalized = {
        "schema_version": schema_version,
        "task_type": task_type or payload.get("task_type") or "qa",
        "input_fields": mapped_input,
        "expected_fields": mapped_expected,
        "metadata_fields": mapped_metadata,
        "required_fields": _field_list(
            required_fields if required_fields is not None else payload.get("required_fields")
        ),
        "field_types": _json_object(
            field_types if field_types is not None else payload.get("field_types"),
            "field_types",
        ),
        "answer_policy": _json_object(
            answer_policy if answer_policy is not None else payload.get("answer_policy"),
            "answer_policy",
        ),
    }
    normalized["field_mapping"] = {
        "input_fields": normalized["input_fields"],
        "expected_fields": normalized["expected_fields"],
        "metadata_fields": normalized["metadata_fields"],
    }
    return normalized


def _source_has_field(row: dict, field: str) -> bool:
    if field in row and row[field] not in (None, ""):
        return True
    expected = row.get("expected")
    return isinstance(expected, dict) and expected.get(field) not in (None, "")


def validate_required_fields(row: dict, contract: dict, row_idx: int) -> list[str]:
    issues: list[str] = []
    for field in contract.get("required_fields", []) or []:
        if not _source_has_field(row, field):
            issues.append(f"Row {row_idx} missing required field: {field}")
    return issues


def split_input_expected(row: dict, contract: dict | None = None) -> tuple[dict, dict | None]:
    """Separate a dataset row into input fields and expected answer fields.

    Strategy:
    1. If the row contains an explicit ``expected`` key (a dict/list), treat it as
       the full expected structure and put everything else into input.
    2. Otherwise, scan for known answer-key names and collect them into a single
       expected dict. All other keys become input.
    3. If no expected key is found, treat the entire row as input with no expected.

    This handles common formats:

    * ``{"question": "...", "answer": "北京"}`` → input={question}, expected={answer:北京}
    * ``{"prompt": "...", "answer": "北京", "reasoning": "..."}`` → input={prompt}, expected={answer:北京, reasoning:...}
    * ``{"text": "...", "label": "正面"}`` → input={text}, expected={label:正面}
    * ``{"question": "...", "expected": {"answer": "北京"}}`` → input={question}, expected={answer:北京}
    """
    source = dict(row)
    mapping = (contract or {}).get("field_mapping", contract or {})
    input_fields = mapping.get("input_fields") or []
    expected_fields = mapping.get("expected_fields") or []
    metadata_fields = mapping.get("metadata_fields") or []

    if input_fields or expected_fields or metadata_fields:
        input_data = {field: source[field] for field in input_fields if field in source}
        metadata = {field: source[field] for field in metadata_fields if field in source}
        if metadata:
            input_data["_metadata"] = metadata

        expected: dict = {}
        nested_expected = source.get("expected")
        for field in expected_fields:
            if field == "expected" and "expected" in source:
                expected_val = source["expected"]
                if isinstance(expected_val, dict):
                    expected.update(expected_val)
                elif isinstance(expected_val, list):
                    expected["answer"] = expected_val
                else:
                    expected["answer"] = expected_val
            elif field in source:
                expected[field] = source[field]
            elif isinstance(nested_expected, dict) and field in nested_expected:
                expected[field] = nested_expected[field]
        return input_data, expected or None

    # Step 1: Check for explicit "expected" key (could be a dict or list).
    if "expected" in source:
        expected_val = source.pop("expected")
        if isinstance(expected_val, dict):
            return source, expected_val
        elif isinstance(expected_val, list):
            # Wrap list of answers into a single expected dict.
            return source, {"answer": expected_val}
        else:
            return source, {"answer": expected_val}

    # Step 2: Look for known answer keys and collect them.
    expected_keys = set()
    for key in source:
        if key in _EXPECTED_KEYS:
            expected_keys.add(key)

    if expected_keys:
        expected = {}
        remaining = {}
        for key, value in source.items():
            if key in expected_keys:
                expected[key] = value
            else:
                remaining[key] = value
        return remaining, expected if expected else None

    # Step 3: No expected fields found — treat entire row as input.
    return source, None
