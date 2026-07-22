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
    # Step 1: Check for explicit "expected" key (could be a dict or list).
    if "expected" in row:
        expected_val = row.pop("expected")
        if isinstance(expected_val, dict):
            return row, expected_val
        elif isinstance(expected_val, list):
            # Wrap list of answers into a single expected dict.
            return row, {"answer": expected_val}
        else:
            return row, {"answer": expected_val}

    # Step 2: Look for known answer keys and collect them.
    expected_keys = set()
    for key in row:
        if key in _EXPECTED_KEYS:
            expected_keys.add(key)

    if expected_keys:
        expected = {}
        remaining = {}
        for key, value in row.items():
            if key in expected_keys:
                expected[key] = value
            else:
                remaining[key] = value
        return remaining, expected if expected else None

    # Step 3: No expected fields found — treat entire row as input.
    return row, None
