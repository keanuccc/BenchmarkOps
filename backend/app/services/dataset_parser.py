"""Pure parsing helpers for dataset import (no DB access)."""
from __future__ import annotations

import csv
import io
import json

from app.core.exceptions import ValidationError

_EXPECTED_KEYS = ("expected", "answer", "label", "output", "target", "ground_truth")
_SUPPORTED = ("csv", "json", "jsonl")


def parse_dataset(raw_bytes: bytes, fmt: str) -> list[dict]:
    fmt = (fmt or "").strip().lower()
    if fmt not in _SUPPORTED:
        raise ValidationError(f"Unsupported format: {fmt!r}")

    text = raw_bytes.decode("utf-8")
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


def split_input_expected(row: dict) -> tuple[dict, dict | None]:
    for key in _EXPECTED_KEYS:
        if key in row:
            expected = {key: row[key]}
            remaining = {k: v for k, v in row.items() if k != key}
            return remaining, expected
    return row, None
