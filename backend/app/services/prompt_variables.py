"""Prompt template variable parsing and safe rendering (including nested paths).

Supports ``{name}``, ``{user.name}`` and ``{items.0}`` paths. Dict/list values
are serialized to JSON; ``None`` renders as an empty string; ``{{``/``}}`` are
escaped braces exactly like ``str.format``.
"""
from __future__ import annotations

import json
import re
from typing import Any

_VAR_RE = re.compile(
    r"\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\.[0-9]+)*)\}"
)
_ESC_OPEN = "\x00"
_ESC_CLOSE = "\x01"


def extract_variables(template: str) -> list[str]:
    seen: list[str] = []
    for match in _VAR_RE.findall(template):
        if match not in seen:
            seen.append(match)
    return seen


def variable_root(path: str) -> str:
    """Return the top-level field a variable path lives under."""
    return path.split(".", 1)[0]


def _resolve(variables: dict, path: str) -> Any:
    current: Any = variables
    for segment in path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                raise KeyError(path)
            current = current[segment]
        elif isinstance(current, (list, tuple)) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                raise IndexError(path)
            current = current[index]
        else:
            raise KeyError(path)
    return current


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_template(template: str, variables: dict) -> str:
    """Substitute all ``{path}`` placeholders; raises KeyError/IndexError."""
    escaped = template.replace("{{", _ESC_OPEN).replace("}}", _ESC_CLOSE)

    def _sub(match: re.Match) -> str:
        return _stringify(_resolve(variables, match.group(1)))

    rendered = _VAR_RE.sub(_sub, escaped)
    return rendered.replace(_ESC_OPEN, "{").replace(_ESC_CLOSE, "}")
