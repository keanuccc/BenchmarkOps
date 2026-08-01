"""Regression tests for robust answer matching and scoring semantics."""
from __future__ import annotations

import asyncio

import pytest

from app.core.exceptions import ValidationError
from app.evaluation.metrics import (
    MetricEvaluationError,
    exact_match,
    exact_match_ci,
    contains,
    fuzzy_match,
    f1_token,
    has_metric_suite,
    llm_judge,
    numeric_match,
    validate_metric_suite,
)
from app.evaluation.runner import _extract_answer, _first_value, _score_reason
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider


def test_exact_match_normalizes_expected_units_symmetrically() -> None:
    prediction = _extract_answer("答案：40平方厘米")

    assert exact_match_ci(prediction, "40平方厘米") == 1.0


def test_exact_match_remains_case_and_whitespace_sensitive() -> None:
    assert exact_match("Paris", "paris") == 0.0
    assert exact_match("NewYork", "New York") == 0.0
    assert exact_match("", "") == 0.0


def test_answer_policy_can_preserve_units_during_extraction() -> None:
    assert _extract_answer("答案：100m", strip_units=False) == "100m"


def test_first_value_prefers_nested_value_over_metadata_order() -> None:
    assert _first_value({"confidence": 0.9, "value": "Paris"}) == "Paris"


def test_metric_suite_rejects_duplicate_or_non_finite_weights() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        validate_metric_suite(
            "exact_match_ci",
            {
                "metric_suite": [
                    {"name": "exact_match_ci", "weight": 1},
                    {"name": "exact_match_ci", "weight": 1},
                ]
            },
        )
    with pytest.raises(ValidationError, match="finite"):
        validate_metric_suite(
            "exact_match_ci",
            {"metric_suite": [{"name": "exact_match_ci", "weight": "NaN"}]},
        )


def test_metric_suite_detection_includes_snapshot_spec() -> None:
    assert not has_metric_suite(
        {}, {"metric_suite": [{"name": "exact_match_ci", "weight": 1.0}]}
    )
    assert has_metric_suite(
        {},
        {
            "metric_suite_explicit": True,
            "metric_suite": [{"name": "exact_match_ci", "weight": 1.0}],
        },
    )
def test_exact_match_ci_accepts_aliases_from_answer_policy() -> None:
    assert exact_match_ci(
        "Beijing",
        "北京",
        expected_raw={"answer": "北京"},
        answer_policy={"aliases": ["Beijing"]},
    ) == 1.0


def test_empty_expected_never_matches_a_policy_alias() -> None:
    assert exact_match_ci(
        "Beijing",
        "",
        answer_policy={"aliases": ["Beijing"]},
    ) == 0.0


def test_exact_match_ci_requires_all_answers_when_policy_requests_it() -> None:
    assert exact_match_ci(
        "A, B",
        "A",
        expected_raw={"answer": ["A", "B"]},
        answer_policy={"multi_answer": "all"},
    ) == 1.0


def test_contains_does_not_match_inside_a_larger_ascii_word() -> None:
    from app.evaluation.metrics import contains

    assert contains("concatenate", "cat") == 0.0
    assert contains("The cat sat", "cat") == 1.0
    assert contains("北京大学", "北京") == 0.0


def test_f1_token_counts_duplicate_tokens_and_ignores_punctuation() -> None:
    assert f1_token("Paris Paris!", "Paris Paris") == pytest.approx(1.0)


def test_answer_policy_aliases_apply_to_f1_and_numeric_metrics() -> None:
    assert f1_token(
        "Lutetia",
        "Paris",
        answer_policy={"aliases": ["Lutetia"]},
    ) == 1.0


def test_multi_answer_all_is_consistent_across_text_metrics() -> None:
    raw = {"answer": ["A", "B"]}
    policy = {"multi_answer": "all"}

    assert contains("A", "A", expected_raw=raw, answer_policy=policy) == 0.0
    assert f1_token("A", "A", expected_raw=raw, answer_policy=policy) < 1.0
    assert numeric_match("1", "1", expected_raw={"answer": ["1", "2"]}, answer_policy=policy) == 0.0


def test_fuzzy_match_uses_answer_policy_and_validates_threshold() -> None:
    assert fuzzy_match(
        "Lutetia",
        "Paris",
        answer_policy={"aliases": ["Lutetia"]},
    ) == 1.0
    with pytest.raises(ValidationError, match="threshold"):
        fuzzy_match("Paris", "Paris", threshold=-0.1)
    assert numeric_match(
        "1.5e3",
        "not numeric",
        answer_policy={"accepted_answers": ["1.5e3"]},
    ) == 1.0


def test_llm_judge_reuses_cached_result(monkeypatch) -> None:
    calls = 0

    class Provider:
        async def complete(self, request):  # noqa: ANN001
            nonlocal calls
            calls += 1
            return type("Result", (), {"text": "MATCH"})()

    monkeypatch.setattr("app.providers.registry.get_provider", lambda name=None: Provider())

    first = asyncio.run(llm_judge("cache-pred-unique", "cache-exp-unique", judge_provider="mock"))
    second = asyncio.run(llm_judge("cache-pred-unique", "cache-exp-unique", judge_provider="mock"))

    assert first == second == 1.0
    assert calls == 1


def test_llm_judge_rejects_ambiguous_substrings(monkeypatch) -> None:
    class Provider:
        async def complete(self, request):  # noqa: ANN001
            return type("Result", (), {"text": "UNTRUE"})()

    monkeypatch.setattr("app.providers.registry.get_provider", lambda name=None: Provider())

    assert asyncio.run(
        llm_judge(
            "judge-pred-unique",
            "judge-exp-unique",
            judge_provider="mock",
            judge_model="judge-model-unique",
        )
    ) == 0.0


def test_llm_judge_can_surface_provider_failures_to_the_runner(monkeypatch) -> None:
    class Provider:
        async def complete(self, request):  # noqa: ANN001
            raise TimeoutError("judge timeout")

    monkeypatch.setattr("app.providers.registry.get_provider", lambda name=None: Provider())

    with pytest.raises(MetricEvaluationError, match="judge timeout"):
        asyncio.run(
            llm_judge(
                "judge-pred-provider-error",
                "judge-exp-provider-error",
                judge_provider="mock",
                raise_on_error=True,
            )
        )


def test_score_reason_describes_non_exact_metric_behavior() -> None:
    reason = _score_reason("contains", 1.0, "The cat sat", "cat")

    assert "contains" in reason
    assert "substring" in reason


def test_runner_applies_dataset_answer_policy(client, monkeypatch) -> None:
    class AliasProvider(LLMProvider):
        name = "mock"

        async def complete(self, request: CompletionRequest) -> CompletionResult:
            return CompletionResult(text="Beijing", prompt_tokens=1, completion_tokens=1)

    monkeypatch.setattr("app.evaluation.runner.get_provider", lambda name=None: AliasProvider())
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    model_id = client.get("/api/v1/models/").json()[0]["id"]
    project_id = client.post("/api/v1/projects/", json={"name": "PolicyRun"}).json()["id"]
    benchmark_id = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": project_id, "name": "QA", "type": "qa"},
    ).json()["id"]
    prompt_id = client.post(
        "/api/v1/prompts/",
        json={"project_id": project_id, "name": "P", "template": "{question}"},
    ).json()["id"]
    dataset_id = client.post(
        "/api/v1/datasets/upload",
        data={
            "project_id": project_id,
            "name": "DS",
            "format": "jsonl",
            "answer_policy": '{"aliases": ["Beijing"]}',
        },
        files={"file": ("d.jsonl", '{"question":"capital?","answer":"北京"}\n'.encode(), "application/jsonl")},
    ).json()["id"]
    experiment_id = client.post(
        "/api/v1/experiments/",
        json={
            "project_id": project_id,
            "name": "E",
            "dataset_id": dataset_id,
            "benchmark_id": benchmark_id,
            "prompt_id": prompt_id,
            "model_id": model_id,
        },
    ).json()["id"]

    from app.evaluation.runner import run_experiment

    asyncio.run(run_experiment(experiment_id))
    result = client.get(f"/api/v1/experiments/{experiment_id}/results").json()[0]
    assert result["score"] == 1.0


def test_runner_passes_model_context_to_llm_judge(client, monkeypatch) -> None:
    judge_names: list[str | None] = []
    judge_model_ids: list[str] = []

    class PrimaryProvider(LLMProvider):
        name = "primary"

        async def complete(self, request: CompletionRequest) -> CompletionResult:
            return CompletionResult(text="semantic-answer", prompt_tokens=1, completion_tokens=1)

    class JudgeProvider:
        async def complete(self, request):  # noqa: ANN001
            judge_model_ids.append(request.model_id)
            return type("Result", (), {"text": "MATCH"})()

    monkeypatch.setattr("app.evaluation.runner.get_provider", lambda name=None: PrimaryProvider())

    def get_judge_provider(name=None):
        judge_names.append(name)
        return JudgeProvider()

    monkeypatch.setattr("app.providers.registry.get_provider", get_judge_provider)
    model = client.post(
        "/api/v1/models/",
        json={
            "name": "Judge target",
            "provider": "qiniu",
            "model_id": "judge-target-unique",
            "pricing": {},
        },
    ).json()
    project_id = client.post("/api/v1/projects/", json={"name": "JudgeContext"}).json()["id"]
    benchmark_id = client.post(
        "/api/v1/benchmarks/",
        json={
            "project_id": project_id,
            "name": "Judge",
            "type": "qa",
            "metric": "llm_judge",
        },
    ).json()["id"]
    prompt_id = client.post(
        "/api/v1/prompts/",
        json={"project_id": project_id, "name": "P", "template": "{question}"},
    ).json()["id"]
    dataset_id = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": project_id, "name": "DS", "format": "jsonl"},
        files={"file": ("d.jsonl", b'{"question":"q","answer":"semantic-answer"}\n', "application/jsonl")},
    ).json()["id"]
    experiment_id = client.post(
        "/api/v1/experiments/",
        json={
            "project_id": project_id,
            "name": "E",
            "dataset_id": dataset_id,
            "benchmark_id": benchmark_id,
            "prompt_id": prompt_id,
            "model_id": model["id"],
        },
    ).json()["id"]

    from app.evaluation.runner import run_experiment

    asyncio.run(run_experiment(experiment_id))
    assert judge_names == ["qiniu"]
    assert judge_model_ids == ["judge-target-unique"]
