"""Tests for markdown code-fence extraction in the evaluation runner."""
from __future__ import annotations

from app.evaluation.runner import _extract_code


def test_extract_fenced_python():
    out = '```python\ndef add(a, b):\n    return a + b\n```'
    assert _extract_code(out) == "def add(a, b):\n    return a + b"


def test_extract_fenced_without_language():
    out = "```\ndef f():\n    return 1\n```"
    assert _extract_code(out) == "def f():\n    return 1"


def test_extract_multiple_fences_takes_blocks():
    out = "```python\na = 1\n```\n```python\nb = 2\n```"
    assert _extract_code(out) == "a = 1\n\nb = 2"


def test_plain_code_untouched():
    code = "def f():\n    return 1\n"
    assert _extract_code(code) == code.strip()


def test_stray_fence_removed():
    assert _extract_code("```\ndef f():\n    pass\n```") == "def f():\n    pass"


def test_empty():
    assert _extract_code("") == ""
