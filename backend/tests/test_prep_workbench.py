"""Tests for the evaluation-preparation workbench (stateless prep endpoints)."""
from __future__ import annotations

from app.evaluation.runner import _extract_answer
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider
from app.services.prep_service import _row_signals


class _FixedProvider(LLMProvider):
    def __init__(self, text: str):
        self.text = text

    name = "fixed"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(
            text=self.text,
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=5,
        )


def _upload_jsonl(client, filename: str, content: str):
    return client.post(
        "/api/v1/prep/analyze",
        data={"format": "jsonl"},
        files={"file": (filename, content.encode("utf-8"), "application/x-ndjson")},
    )


def test_analyze_suggests_answer_and_sensitive_columns(client):
    content = (
        '{"question": "2+2等于几？", "answer": "4", "手机号": "13800000000"}\n'
        '{"question": "3+3等于几？", "answer": "6", "手机号": "13900000000"}\n'
    )
    resp = _upload_jsonl(client, "qa.jsonl", content)
    assert resp.status_code == 200
    data = resp.json()
    assert data["row_count"] == 2
    assert data["format"] == "jsonl"
    assert "answer" in data["suggestions"]["answer_candidates"]
    assert "手机号" in data["suggestions"]["sensitive_candidates"]
    assert data["suggestions"]["task_type"] == "qa"
    assert data["suggestions"]["structured_chat"] is False


def test_analyze_detects_chat_and_classification(client):
    content = (
        '{"messages": [{"role": "user", "content": "我要退货"}], "label": "售后"}\n'
    )
    resp = _upload_jsonl(client, "chat.jsonl", content)
    assert resp.status_code == 200
    data = resp.json()
    assert data["suggestions"]["structured_chat"] is True
    assert data["suggestions"]["task_type"] == "classification"


def test_analyze_rejects_empty_file(client):
    resp = _upload_jsonl(client, "empty.jsonl", "")
    # FastAPI rejects empty multipart files at the request layer (422); the
    # service also rejects empty datasets (400) if the file reaches it.
    assert resp.status_code in (400, 422)


def test_transform_builds_contract_and_preview(client):
    content = '{"question": "2+2等于几？", "answer": "4"}\n'
    config = {
        "task_type": "qa",
        "input_fields": ["question"],
        "expected_fields": ["answer"],
        "answer_policy": {"multi_answer": "all", "partial_credit": True},
    }
    resp = client.post(
        "/api/v1/prep/transform",
        data={"format": "jsonl", "config": __import__("json").dumps(config)},
        files={"file": ("qa.jsonl", content.encode("utf-8"), "application/x-ndjson")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_rows"] == 1
    assert data["preview"][0]["input"] == {"question": "2+2等于几？"}
    assert data["preview"][0]["expected"] == {"answer": "4"}
    assert data["contract"]["answer_policy"] == config["answer_policy"]
    assert data["import_errors"] == []


def test_transform_reports_import_errors(client):
    content = '{"question": "2+2等于几？", "answer": "4"}\n'
    config = {"required_fields": ["question", "source"]}
    resp = client.post(
        "/api/v1/prep/transform",
        data={"format": "jsonl", "config": __import__("json").dumps(config)},
        files={"file": ("qa.jsonl", content.encode("utf-8"), "application/x-ndjson")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["import_errors"]
    assert "source" in data["import_errors"][0]["message"]


def test_dry_run_scores_rows_without_persisting(client, monkeypatch):
    monkeypatch.setattr(
        "app.providers.registry.get_provider",
        lambda name=None: _FixedProvider("答案：4"),
    )
    payload = {
        "rows": [
            {"question": "2+2等于几？", "answer": "4"},
            {"question": "3+3等于几？", "answer": "9"},
        ],
        "contract": {"input_fields": ["question"], "expected_fields": ["answer"]},
        "template": "问题：{question}\n答案：",
        "benchmark_type": "qa",
        "metric": "exact_match_ci",
        "model_id": "test-model",
        "provider": "mock",
        "sample_size": 2,
    }
    resp = client.post("/api/v1/prep/dry-run", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["rows_total"] == 2
    assert data["summary"]["full_score"] == 1
    assert data["summary"]["avg_score"] == 0.5
    assert data["results"][0]["cleaned_prediction"] == "4"
    assert all("prefix_not_cleaned" not in r["signals"] for r in data["results"])


def test_dry_run_flags_comma_truncation_for_generation(client, monkeypatch):
    monkeypatch.setattr(
        "app.providers.registry.get_provider",
        lambda name=None: _FixedProvider("城市发布人才引进政策，最高200万安家补贴。"),
    )
    payload = {
        "rows": [
            {
                "article": "城市发布人才引进政策。",
                "answer": "城市发布人才引进政策，最高200万安家补贴。",
            }
        ],
        "contract": {"input_fields": ["article"], "expected_fields": ["answer"]},
        "template": "文章：{article}",
        "benchmark_type": "generation",
        "metric": "f1_token",
        "model_id": "test-model",
        "provider": "mock",
        "sample_size": 1,
    }
    resp = client.post("/api/v1/prep/dry-run", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    codes = {s["code"] for s in data["signals"]}
    assert "comma_truncated" in codes
    # The signal is tied to the buggy extraction path, not a real model failure.
    assert data["results"][0]["cleaned_prediction"] == "城市发布人才引进政策"


def test_dry_run_flags_rows_without_expected(client, monkeypatch):
    monkeypatch.setattr(
        "app.providers.registry.get_provider",
        lambda name=None: _FixedProvider("ok"),
    )
    payload = {
        "rows": [{"question": "没有答案的问题"}],
        "contract": {"input_fields": ["question"], "expected_fields": []},
        "template": "{question}",
        "benchmark_type": "qa",
        "metric": "exact_match_ci",
        "model_id": "test-model",
        "provider": "mock",
        "sample_size": 1,
    }
    resp = client.post("/api/v1/prep/dry-run", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    codes = {s["code"] for s in data["signals"]}
    assert "no_expected" in codes


def test_dry_run_respects_sample_size(client, monkeypatch):
    monkeypatch.setattr(
        "app.providers.registry.get_provider",
        lambda name=None: _FixedProvider("yes"),
    )
    rows = [{"question": f"q{i}", "answer": "yes"} for i in range(5)]
    payload = {
        "rows": rows,
        "contract": {"input_fields": ["question"], "expected_fields": ["answer"]},
        "template": "{question}",
        "benchmark_type": "qa",
        "metric": "exact_match_ci",
        "model_id": "test-model",
        "provider": "mock",
        "sample_size": 2,
    }
    resp = client.post("/api/v1/prep/dry-run", json=payload)
    assert resp.status_code == 200
    assert resp.json()["summary"]["rows_total"] == 2


def test_row_signals_prefix_not_cleaned():
    signals = _row_signals(
        output="答案：4",
        cleaned="答案：4",
        expected="4",
        metric_name="exact_match_ci",
    )
    assert "prefix_not_cleaned" in signals


def test_extract_answer_still_strips_prefix_in_dry_run_path():
    # The health signal only fires when extraction failed; normal extraction
    # strips the prefix so a correct answer should not be flagged.
    cleaned = _extract_answer("答案：4", normalize_whitespace=False).strip()
    signals = _row_signals(
        output="答案：4",
        cleaned=cleaned,
        expected="4",
        metric_name="exact_match_ci",
    )
    assert cleaned == "4"
    assert "prefix_not_cleaned" not in signals
