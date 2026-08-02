"""Nested prompt variable paths: extraction, resolution, JSON rendering."""
from __future__ import annotations

import pytest

from app.evaluation.runner import _render_prompt
from app.services.prompt_service import extract_variables
from app.services.prompt_variables import render_template as render_prompt


def test_extract_variables_supports_dotted_paths_and_indexes() -> None:
    template = "User {user.name} lives in {user.address.city}; first item: {items.0}"
    assert extract_variables(template) == [
        "user.name",
        "user.address.city",
        "items.0",
    ]


def test_extract_variables_still_handles_plain_names() -> None:
    assert extract_variables("Answer {question} in {language}") == [
        "question",
        "language",
    ]


def test_render_nested_path_resolves_value() -> None:
    assert (
        render_prompt(
            "Hello {user.name}!",
            {"user": {"name": "Bob", "address": {"city": "Shanghai"}}},
        )
        == "Hello Bob!"
    )


def test_render_serializes_dict_values_as_json() -> None:
    rendered = render_prompt("Context: {user}", {"user": {"name": "Bob"}})
    assert rendered == 'Context: {"name": "Bob"}'


def test_render_resolves_list_index() -> None:
    assert render_prompt("First: {items.0}", {"items": ["a", "b"]}) == "First: a"


def test_render_missing_root_raises_key_error() -> None:
    with pytest.raises(KeyError):
        render_prompt("{user.name}", {})


def test_render_none_becomes_empty_string() -> None:
    assert render_prompt("[{answer}]", {"answer": None}) == "[]"


def test_render_preserves_escaped_braces() -> None:
    assert render_prompt("{{literal}} {question}", {"question": "q"}) == "{literal} q"


def test_runner_falls_back_to_row_dump_when_path_missing() -> None:
    rendered = _render_prompt("Hello {user.name}", ["user.name"], {"question": "q"})
    assert "question: q" in rendered


def test_prompt_service_renders_nested_variables() -> None:
    assert (
        render_prompt(
            "{user.name}: {user.address.city}",
            {"user": {"name": "Bob", "address": {"city": "Shanghai"}}},
        )
        == "Bob: Shanghai"
    )
