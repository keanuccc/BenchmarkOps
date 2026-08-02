"""Shared value redaction for declared sensitive dataset fields."""
from __future__ import annotations

from collections.abc import Set


def redact_values(value: dict, sensitive: Set[str]) -> dict:
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
