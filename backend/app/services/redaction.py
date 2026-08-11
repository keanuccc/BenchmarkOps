"""Shared value redaction for declared sensitive dataset fields.

Two layers:
1. Field-level: a key declared in ``sensitive`` is replaced wholesale with
   ``[REDACTED]`` (top-level and inside ``_metadata``).
2. Text-level: any string value is scanned for common PII patterns (Chinese
   mobile numbers, e-mail addresses) and those substrings are masked, so
   sensitive data written inside a question/answer text is not leaked either.
"""
from __future__ import annotations

import re
from collections.abc import Set

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PII_PATTERNS = (_PHONE_RE, _EMAIL_RE)
_MASK = "[REDACTED]"


def _redact_text(text: str) -> str:
    for pattern in _PII_PATTERNS:
        text = pattern.sub(_MASK, text)
    return text


def _redact_value(value, sensitive: Set[str]):
    if isinstance(value, dict):
        return {
            key: (_MASK if key in sensitive else _redact_value(item, sensitive))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, sensitive) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def redact_values(value: dict, sensitive: Set[str]) -> dict:
    """Mask declared sensitive fields and PII substrings, recursively.

    Text-level PII scanning is only active when at least one sensitive field is
    declared, preserving the contract that undeclared datasets pass through
    unchanged while declared ones get field-level + text-level protection.
    """
    if not sensitive:
        return value
    return _redact_value(value, sensitive)


def redact_text(text: str) -> str:
    """Mask PII substrings in a plain string (model outputs etc.)."""
    return _redact_text(text)
