"""Multi-turn chat history and few-shot examples in evaluation data."""
from __future__ import annotations

import time

import pytest

from app.evaluation.runner import _build_messages


def _project(client, name: str) -> str:
    return client.post("/api/v1/projects/", json={"name": name}).json()["id"]


def _upload(client, pid: str, name: str, rows: bytes, extra: dict | None = None) -> dict:
    data = {"project_id": pid, "name": name, "format": "jsonl"}
    if extra:
        data.update(extra)
    r = client.post(
        "/api/v1/datasets/upload",
        data=data,
        files={"file": (f"{name}.jsonl", rows, "application/x-ndjson")},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _mock_model(client) -> str:
    model = client.post(
        "/api/v1/models/",
        json={
            "name": "mock-mt",
            "provider": "mock",
            "model_id": "mock-mt",
            "is_active": True,
        },
    ).json()
    return model["id"]


def test_structured_chat_flag_roundtrip(client) -> None:
    pid = _project(client, "StructuredFlag")
    ds = _upload(
        client,
        pid,
        "chat",
        b'{"question":"q","answer":"a"}\n',
        extra={"structured_chat": "true"},
    )
    assert ds["contract"]["structured_chat"] is True

    plain = _upload(client, pid, "plain", b'{"question":"q","answer":"a"}\n')
    assert plain["contract"]["structured_chat"] is False


def test_import_rejects_malformed_messages(client) -> None:
    pid = _project(client, "StructuredBad")
    r = client.post(
        "/api/v1/datasets/upload",
        data={
            "project_id": pid,
            "name": "bad-chat",
            "format": "jsonl",
            "structured_chat": "true",
        },
        files={
            "file": (
                "bad.jsonl",
                b'{"question":"q","answer":"a","messages":[{"role":"hacker","content":"x"}]}\n',
                "application/x-ndjson",
            )
        },
    )
    assert r.status_code == 422
    assert "messages" in r.json()["error"]["message"]


def test_import_rejects_non_list_examples(client) -> None:
    pid = _project(client, "StructuredBadExamples")
    r = client.post(
        "/api/v1/datasets/upload",
        data={
            "project_id": pid,
            "name": "bad-examples",
            "format": "jsonl",
            "structured_chat": "true",
        },
        files={
            "file": (
                "bad.jsonl",
                b'{"question":"q","answer":"a","examples":"not-a-list"}\n',
                "application/x-ndjson",
            )
        },
    )
    assert r.status_code == 422
    assert "examples" in r.json()["error"]["message"]


def test_build_messages_assembles_history_and_final_user() -> None:
    messages = _build_messages(
        "{question}",
        ["question"],
        {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
            "question": "2+2?",
        },
        structured_chat=True,
    )
    assert [(m.role, m.content) for m in messages] == [
        ("user", "hi"),
        ("assistant", "hello"),
        ("user", "2+2?"),
    ]


def test_build_messages_renders_few_shot_examples() -> None:
    messages = _build_messages(
        "{question}",
        ["question"],
        {
            "examples": [
                {"question": "1+1?", "answer": "2"},
                "plain example line",
            ],
            "question": "2+2?",
        },
        structured_chat=True,
    )
    final = messages[-1].content
    assert "Q: 1+1?" in final
    assert "A: 2" in final
    assert "plain example line" in final
    assert "2+2?" in final


def test_build_messages_non_structured_preserves_old_behavior() -> None:
    messages = _build_messages(
        "{messages}",
        ["messages"],
        {"messages": [{"role": "user", "content": "hi"}]},
        structured_chat=False,
    )
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert "role" in messages[0].content  # old str.format repr of the list


def test_build_messages_rejects_malformed_history() -> None:
    with pytest.raises(ValueError, match="messages"):
        _build_messages(
            "{question}",
            ["question"],
            {"messages": [{"role": "hacker", "content": "x"}], "question": "q"},
            structured_chat=True,
        )


def test_multiturn_fewshot_end_to_end_mock(client) -> None:
    pid = _project(client, "ChatE2E")
    ds = _upload(
        client,
        pid,
        "chat",
        (
            b'{"question":"2+2?","answer":"4",'
            b'"messages":[{"role":"user","content":"lets go"}],'
            b'"examples":[{"question":"hello","answer":"hi"}]}\n'
            b'{"question":"3*3?","answer":"9"}\n'
        ),
        extra={"structured_chat": "true"},
    )
    bench = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": pid, "name": "QA", "type": "qa", "metric": "exact_match_ci"},
    ).json()
    prompt = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "{question}"},
    ).json()
    model_id = _mock_model(client)
    exp = client.post(
        "/api/v1/experiments/",
        json={
            "project_id": pid,
            "name": "E",
            "dataset_id": ds["id"],
            "benchmark_id": bench["id"],
            "prompt_id": prompt["id"],
            "model_id": model_id,
        },
    ).json()

    client.post(f"/api/v1/experiments/{exp['id']}/run")
    final = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        final = client.get(f"/api/v1/experiments/{exp['id']}").json()
        if final["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert final is not None and final["status"] == "completed", final

    results = client.get(f"/api/v1/experiments/{exp['id']}/results").json()
    assert len(results) == 2
    assert all(r["score"] == 1.0 for r in results)
