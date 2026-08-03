"""Stateless helpers for the evaluation-preparation workbench.

These functions help turn *raw* business files into platform-ready evaluation
data without persisting anything: analyze suggests a mapping, transform builds
the JSONL preview + contract, and dry-run scores a small sample in memory so
users can inspect signals before importing a dataset or running a full
experiment.
"""
from __future__ import annotations

import asyncio
import re

from app.core.exceptions import ValidationError
from app.services.dataset_parser import (
    _EXPECTED_KEYS,
    build_dataset_contract,
    collect_import_errors,
    compute_stats,
    infer_format,
    infer_schema,
    parse_dataset,
    split_input_expected,
)
from app.services.prompt_variables import extract_variables

_SENSITIVE_RE = re.compile(
    r"(手机|电话|phone|mobile|邮箱|email|身份证|idcard|id_card|"
    r"订单|order|地址|address|姓名|name|银行卡|bank)",
    re.IGNORECASE,
)
_ANSWER_NAME_RE = re.compile(
    r"(答案|回复|结论|result|output|target|label|标签|类别|ground|expected)",
    re.IGNORECASE,
)
_ANSWER_PREFIX_RE = re.compile(
    r"^\s*(?:答案|最终答案|结论|Answer|Final Answer)\s*[：:]"
)
_COMMA_TRUNCATION_METRICS = {
    "contains",
    "f1_token",
    "fuzzy_match",
    "fuzzy_match_ci",
    "llm_judge",
    "llm_judge_rubric",
}
_PREVIEW_ROWS = 20


def _suggest_contract(rows: list[dict], columns: list[str]) -> dict:
    """Heuristic suggestions only — the user always confirms before use."""
    lower_to_col = {col.lower(): col for col in columns}
    answer_candidates: list[str] = []
    for key in _EXPECTED_KEYS:
        col = lower_to_col.get(key)
        if col and col not in answer_candidates:
            answer_candidates.append(col)
    for col in columns:
        if col not in answer_candidates and _ANSWER_NAME_RE.search(col):
            answer_candidates.append(col)

    sensitive_candidates = [col for col in columns if _SENSITIVE_RE.search(col)]
    structured_chat = any(
        isinstance(row.get("messages"), list) for row in rows[:100]
    )

    task_type = "qa"
    if answer_candidates:
        first = answer_candidates[0].lower()
        if any(k in first for k in ("label", "标签", "类别", "分类")):
            task_type = "classification"
        elif any(k in first for k in ("prompt", "代码", "code")):
            task_type = "coding"
        else:
            lengths = [
                len(str(row.get(answer_candidates[0], "")))
                for row in rows[:100]
                if row.get(answer_candidates[0])
            ]
            if lengths and sum(lengths) / len(lengths) > 40:
                task_type = "generation"

    multi_answer = any(
        isinstance(row.get(col), list)
        for col in answer_candidates
        for row in rows[:100]
    )
    return {
        "answer_candidates": answer_candidates,
        "sensitive_candidates": sensitive_candidates,
        "structured_chat": structured_chat,
        "task_type": task_type,
        "multi_answer": multi_answer,
    }


def analyze_raw_data(
    raw_bytes: bytes,
    *,
    filename: str | None,
    fmt: str | None,
) -> dict:
    """Parse a raw file and return column stats + mapping suggestions."""
    resolved = infer_format(filename, fmt)
    rows = parse_dataset(raw_bytes, resolved)
    if not rows:
        raise ValidationError("Dataset is empty: file contains 0 rows")
    columns = infer_schema(rows)
    return {
        "filename": filename,
        "format": resolved,
        "row_count": len(rows),
        "columns": columns,
        "column_count": len(columns),
        "stats": compute_stats(rows),
        "samples": rows[:_PREVIEW_ROWS],
        "suggestions": _suggest_contract(rows, columns),
    }


def transform_preview(
    raw_bytes: bytes,
    *,
    filename: str | None,
    fmt: str | None,
    config: dict,
) -> dict:
    """Build the platform contract + a split-row preview for a raw file."""
    resolved = infer_format(filename, fmt)
    rows = parse_dataset(raw_bytes, resolved)
    if not rows:
        raise ValidationError("Dataset is empty: file contains 0 rows")

    contract = build_dataset_contract(
        rows,
        task_type=config.get("task_type"),
        input_fields=config.get("input_fields"),
        expected_fields=config.get("expected_fields"),
        metadata_fields=config.get("metadata_fields"),
        required_fields=config.get("required_fields"),
        field_types=config.get("field_types"),
        answer_policy=config.get("answer_policy"),
        sensitive_fields=config.get("sensitive_fields"),
        structured_chat=config.get("structured_chat"),
    )
    import_errors = collect_import_errors(rows, contract)
    preview: list[dict] = []
    for row in rows[:_PREVIEW_ROWS]:
        row_input, expected = split_input_expected(row, contract)
        preview.append({"input": row_input, "expected": expected})
    return {
        "total_rows": len(rows),
        "preview": preview,
        "raw_preview": rows[:_PREVIEW_ROWS],
        "contract": contract,
        "import_errors": import_errors[:100],
    }


def _row_signals(
    *,
    output: str,
    cleaned: str,
    expected: str,
    metric_name: str,
) -> list[str]:
    signals: list[str] = []
    if not expected:
        signals.append("no_expected")
    if not output.strip():
        signals.append("empty_output")
    elif _ANSWER_PREFIX_RE.search(output) and cleaned == output.strip():
        signals.append("prefix_not_cleaned")
    if (
        metric_name in _COMMA_TRUNCATION_METRICS
        and ("，" in output or "," in output)
        and cleaned
        and len(cleaned) < len(output.strip())
        and cleaned != expected.strip()
    ):
        # The extractor only keeps the first comma-segment; for long-form
        # metrics that usually means the prediction was wrongly truncated.
        first = output.split("，", 1)[0].split(",", 1)[0].strip()
        if cleaned == first:
            signals.append("comma_truncated")
    return signals


async def dry_run_rows(
    rows: list[dict],
    *,
    contract: dict,
    template: str,
    benchmark_type: str,
    metric: str,
    metric_config: dict | None = None,
    model_id: str,
    provider_name: str,
    params: dict | None = None,
    sample_size: int = 20,
) -> dict:
    """Score a small in-memory sample (no DB writes, no experiment record)."""
    from app.evaluation.metrics import _call_metric, get_metric, normalize_metric_suite
    from app.evaluation.runner import _build_messages, _extract_answer, _first_value
    from app.providers.base import CompletionRequest
    from app.providers.registry import get_provider
    from app.core.config import settings

    if not rows:
        raise ValidationError("No rows to dry-run")
    if not template.strip():
        raise ValidationError("Prompt template is required for dry-run")
    if not metric:
        raise ValidationError("Metric is required for dry-run")

    sample = rows[: max(1, min(int(sample_size), len(rows)))]
    variables = extract_variables(template)
    suite = normalize_metric_suite(metric, metric_config or {}, {})
    metric_fns = {item["name"]: get_metric(item["name"]) for item in suite}
    total_weight = sum(item["weight"] for item in suite) or 1.0
    answer_policy = (contract or {}).get("answer_policy", {}) or {}
    structured_chat = bool((contract or {}).get("structured_chat", False))

    try:
        provider = get_provider(provider_name)
    except Exception as exc:
        raise ValidationError(f"Provider unavailable: {exc}") from exc

    temperature = float((params or {}).get("temperature", 0.0))
    max_tokens = (params or {}).get("max_tokens")
    timeout = getattr(settings, "eval_request_timeout", 120)

    results: list[dict] = []
    for row_idx, row in enumerate(sample):
        row_input, expected = split_input_expected(row, contract)
        expected_str = _first_value(expected)
        entry = {
            "row_idx": row_idx,
            "input": row_input,
            "expected": expected,
            "output": "",
            "cleaned_prediction": "",
            "expected_canonical": expected_str,
            "score": 0.0,
            "score_reason": "",
            "error": None,
            "signals": [],
        }
        try:
            messages = _build_messages(
                template,
                variables,
                row_input,
                structured_chat=structured_chat,
            )
            completion = await asyncio.wait_for(
                provider.complete(
                    CompletionRequest(
                        model_id=model_id,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                ),
                timeout=timeout,
            )
        except Exception as exc:
            entry["error"] = str(exc)[:500]
            entry["signals"] = ["row_error"]
            results.append(entry)
            continue

        output = completion.text or ""
        multi_answer = answer_policy.get("multi_answer")
        cleaned = _extract_answer(
            output,
            split_commas=multi_answer not in ("all", "set"),
            normalize_whitespace=False,
            strip_units=answer_policy.get("strip_units", True),
        ).strip()
        entry["output"] = output
        entry["cleaned_prediction"] = cleaned
        entry["signals"] = _row_signals(
            output=output,
            cleaned=cleaned,
            expected=expected_str,
            metric_name=metric,
        )

        metric_scores: dict[str, float] = {}
        weighted = 0.0
        for item in suite:
            kwargs = dict(item["config"])
            kwargs.setdefault("benchmark_type", benchmark_type)
            kwargs.setdefault("model_id", model_id)
            kwargs.setdefault("provider", provider_name)
            kwargs.setdefault("answer_policy", answer_policy)
            kwargs["raise_on_error"] = True
            try:
                metric_score = float(
                    await _call_metric(
                        metric_fns[item["name"]],
                        cleaned,
                        expected_str,
                        expected_raw=expected,
                        **kwargs,
                    )
                )
            except Exception as exc:
                entry["error"] = f"metric_error: {exc}"[:500]
                entry["signals"].append("row_error")
                break
            metric_scores[item["name"]] = metric_score
            weighted += metric_score * item["weight"]
        else:
            score = weighted / total_weight
            entry["score"] = max(0.0, min(1.0, score))
            entry["score_reason"] = (
                f"{metric}: {'matched' if score >= 1.0 else 'did not match'} "
                f"({entry['cleaned_prediction'][:60]!r} vs {expected_str[:60]!r})"
            )
        results.append(entry)

    scored = [r for r in results if r["error"] is None]
    summary = {
        "rows_total": len(results),
        "rows_run": len(results),
        "rows_scored": len(scored),
        "avg_score": round(sum(r["score"] for r in scored) / len(scored), 4) if scored else 0.0,
        "full_score": sum(1 for r in scored if r["score"] >= 1.0),
        "zero_score": sum(1 for r in scored if r["score"] == 0.0),
        "row_errors": sum(1 for r in results if r["error"] is not None),
    }

    signal_counts: dict[str, list[int]] = {}
    for idx, r in enumerate(results):
        for code in r["signals"]:
            signal_counts.setdefault(code, []).append(idx)
    labels = {
        "no_expected": "无标准答案（无法评分）",
        "empty_output": "模型输出为空",
        "prefix_not_cleaned": "输出带“答案：”前缀但未被清洗",
        "comma_truncated": "长文本疑似被逗号截断",
        "row_error": "行执行出错",
    }
    signals = [
        {"code": code, "label": labels.get(code, code), "count": len(idxs), "rows": idxs}
        for code, idxs in sorted(signal_counts.items())
    ]
    return {"results": results, "summary": summary, "signals": signals}
