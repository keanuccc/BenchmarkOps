"""Report generation logic.

Two paths:
- `template_report`: deterministic, zero-LLM Markdown (default in dev).
- `ai_report`: LLM-generated Markdown, falls back on failure.

Both return (markdown, sections_dict) where sections_dict has the SIX keys.
"""
from __future__ import annotations

import json

from app.models.experiment import Experiment, ExperimentResult
from app.providers.base import ChatMessage, CompletionRequest, LLMProvider
from app.schemas.experiment import _sanitize_error


def build_context(
    experiments: list[Experiment],
    results_by_exp: dict[str, list[ExperimentResult]],
    model_names: dict[str, str],
) -> dict:
    """Assemble a compact, JSON-serializable summary of the experiments.

    Per experiment: name, model_name, metrics, cost, tokens, runtime, plus up to
    five sample failures (score < 1 or error).
    """
    exp_summaries = []
    for exp in experiments:
        results = results_by_exp.get(exp.id, [])
        failures = []
        for r in results:
            if len(failures) >= 5:
                break
            if (r.error is not None and r.error != "") or (r.score is not None and r.score < 1):
                failures.append(
                    {
                        "row_idx": r.row_idx,
                        "input": r.input,
                        "expected": r.expected,
                        "output": r.output,
                        "score": r.score,
                        "error": _sanitize_error(r.error),
                    }
                )
        exp_summaries.append(
            {
                "id": exp.id,
                "name": exp.name,
                "model_id": exp.model_id,
                "model_name": model_names.get(exp.model_id, exp.model_id),
                "metrics": exp.metrics or {},
                "total_cost": exp.total_cost,
                "total_tokens": exp.total_tokens,
                "runtime_ms": exp.runtime_ms,
                "status": exp.status,
                "error": _sanitize_error(exp.error),
                "failures": failures,
            }
        )
    return {"experiments": exp_summaries}


def _fmt(v, digits: int = 2) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def template_report(context: dict) -> tuple[str, dict]:
    """Deterministic Markdown report with the six sections. No LLM."""
    exps = context.get("experiments", [])

    # Derive data-driven insights.
    by_acc = sorted(
        [e for e in exps if isinstance(e.get("metrics", {}).get("accuracy"), (int, float))],
        key=lambda e: e["metrics"]["accuracy"],
        reverse=True,
    )
    by_cost = sorted(
        [e for e in exps if isinstance(e.get("total_cost"), (int, float))],
        key=lambda e: e["total_cost"],
    )
    total_cost = sum(e.get("total_cost") or 0 for e in exps)
    total_tokens = sum(e.get("total_tokens") or 0 for e in exps)
    total_fail = sum(len(e.get("failures") or []) for e in exps)
    high_fail = (
        max(exps, key=lambda e: len(e.get("failures") or []))
        if exps
        else None
    )

    best_acc = by_acc[0] if by_acc else None
    cheapest = by_cost[0] if by_cost else None

    # --- 执行摘要 ---
    exec_lines = [
        f"本报告覆盖 **{len(exps)}** 个实验，"
        f"总花费 **${_fmt(total_cost)}**，"
        f"共消耗 **{total_tokens}** 个令牌，"
        f"累计运行 **{_fmt(_total_runtime_ms(exps))} 毫秒**。"
    ]
    if best_acc:
        exec_lines.append(
            f"综合准确率最高的是 **{best_acc['name']}** "
            f"（{best_acc['model_name']}），达到 **{_fmt(best_acc['metrics']['accuracy']*100, 1)}%**。"
        )
    if total_fail:
        exec_lines.append(f"共检查了 **{total_fail}** 个失败样本。")
    executive_summary = "\n\n".join(exec_lines)

    # --- 性能分析 ---
    perf_lines = ["| 实验 | 模型 | 准确率 | 平均延迟(毫秒) | 已评分行数 | 失败行数 |",
                  "|---|---|---|---|---|---|"]
    for e in exps:
        m = e.get("metrics", {})
        perf_lines.append(
            f"| {e['name']} | {e['model_name']} | "
            f"{_fmt(_pct(m.get('accuracy')))} | {_fmt(m.get('avg_latency_ms'))} | "
            f"{_fmt(m.get('rows_scored'))} | {_fmt(m.get('rows_failed'))} |"
        )
    performance_analysis = "\n".join(perf_lines)

    # --- 成本分析 ---
    cost_lines = [f"总花费：**${_fmt(total_cost)}**，共 **{total_tokens}** 个令牌。"]
    if cheapest:
        cost_lines.append(
            f"最省钱的实验：**{cheapest['name']}** "
            f"（${_fmt(cheapest['total_cost'])}，{cheapest['model_name']}）。"
        )
    for e in exps:
        cost_lines.append(
            f"- {e['name']}：${_fmt(e.get('total_cost'))} "
            f"（{e.get('total_tokens') or 0} 个令牌）"
        )
    cost_analysis = "\n".join(cost_lines)

    # --- 失败分析 ---
    fail_lines = []
    if total_fail == 0:
        fail_lines.append("在检查的结果中未检测到失败样本。")
    else:
        for e in exps:
            fs = e.get("failures") or []
            if not fs:
                continue
            fail_lines.append(f"### {e['name']} ({e['model_name']})")
            for f in fs:
                fail_lines.append(
                    f"- 第 {f['row_idx']} 行：得分={_fmt(f.get('score'))}，"
                    f"错误={f.get('error') or '得分 < 1'}"
                )
    failure_analysis = "\n".join(fail_lines) if fail_lines else "未记录失败。"

    # --- 建议 ---
    rec_lines = []
    if best_acc:
        rec_lines.append(
            f"在对准确率敏感的场景中，采用 **{best_acc['model_name']}**（{best_acc['name']}）"
            f"作为基线（实测最高准确率为 "
            f"{_fmt(best_acc['metrics']['accuracy']*100, 1)}%）。"
        )
    if cheapest and best_acc and cheapest["name"] != best_acc["name"]:
        rec_lines.append(
            f"在对成本敏感的路径中，可考虑 **{cheapest['model_name']}** "
            f"（${_fmt(cheapest['total_cost'])}）作为更省钱的替代方案。"
        )
    if high_fail and len(high_fail.get("failures") or []):
        rec_lines.append(
            f"排查 **{high_fail['name']}** —— 其失败样本数最多，"
            f"可能需要调整提示词或数据。"
        )
    if not rec_lines:
        rec_lines.append("使用更大的数据集重新运行实验，以获得可对比的指标。")
    recommendations = "\n".join(rec_lines)

    # --- 下一步行动 ---
    next_actions = (
        "1. 逐个实验查看「性能分析」与「失败分析」部分。\n"
        "2. 在质量关键处推广使用准确率最高的模型。\n"
        "3. 针对失败率偏高的实验，调优提示词或筛选逻辑。\n"
        "4. 应用改动后重新生成本报告，以跟踪改进情况。"
    )

    sections = {
        "executive_summary": executive_summary,
        "performance_analysis": performance_analysis,
        "cost_analysis": cost_analysis,
        "failure_analysis": failure_analysis,
        "recommendations": recommendations,
        "next_actions": next_actions,
    }

    markdown = "# AI 评测报告\n\n" + "\n\n".join(
        f"## {_TITLE(key)}\n\n{val}" for key, val in sections.items()
    )
    return markdown, sections


def _pct(v):
    return None if v is None else v * 100


def _TITLE(key: str) -> str:
    return {
        "executive_summary": "执行摘要",
        "performance_analysis": "性能分析",
        "cost_analysis": "成本分析",
        "failure_analysis": "失败分析",
        "recommendations": "建议",
        "next_actions": "下一步行动",
    }[key]


def _total_runtime_ms(exps: list[dict]) -> float:
    return sum(e.get("runtime_ms") or 0 for e in exps)


def _parse_sections(markdown: str) -> dict:
    """Best-effort split of Markdown into the six sections by `## ` headers."""
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    def flush():
        if current_key is not None:
            sections[current_key] = "\n".join(current_lines).strip()

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            flush()
            title = stripped[3:].strip().lower()
            key = _KEY_BY_TITLE.get(title)
            current_key = key
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)
    flush()
    return sections


_KEY_BY_TITLE = {
    "executive summary": "executive_summary",
    "performance analysis": "performance_analysis",
    "cost analysis": "cost_analysis",
    "failure analysis": "failure_analysis",
    "recommendations": "recommendations",
    "next actions": "next_actions",
    # Chinese titles (used by the Chinese AI report prompt).
    "执行摘要": "executive_summary",
    "性能分析": "performance_analysis",
    "成本分析": "cost_analysis",
    "失败分析": "failure_analysis",
    "建议": "recommendations",
    "下一步行动": "next_actions",
    # Accept a leading "# " title line too.
}


async def ai_report(
    context: dict, provider: LLMProvider, model_id: str
) -> tuple[str, dict]:
    """LLM-generated report. Raises on empty result or <3 parseable sections."""
    prompt = _build_prompt(context)
    result = await provider.complete(
        CompletionRequest(
            model_id=model_id,
            messages=[
                ChatMessage(
                    role="system",
                    content=(
                        "你是一名 AI 评测分析师。请撰写一份清晰、以数据为依据的报告。"
                        "严格按照以下六个 `## ` 章节标题的顺序输出："
                        "执行摘要、性能分析、成本分析、失败分析、建议、下一步行动。"
                        "使用中文，并使用 Markdown 格式。"
                    ),
                ),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=0.2,
        )
    )

    markdown = (result.text or "").strip()
    if not markdown:
        raise ValueError("AI provider returned an empty report")

    # If the model prepended a top-level title, strip the first '# ' line(s).
    sections = _parse_sections(_strip_title(markdown))
    if len(sections) < 3:
        raise ValueError(f"AI report parsed only {len(sections)} sections; expected >= 3")

    # Fill any missing sections with a placeholder so the dict stays complete.
    for key in (
        "executive_summary",
        "performance_analysis",
        "cost_analysis",
        "failure_analysis",
        "recommendations",
        "next_actions",
    ):
        sections.setdefault(key, "")
    return markdown, sections


def _strip_title(markdown: str) -> str:
    lines = markdown.splitlines()
    # Drop a leading single '# Title' line if present.
    if lines and lines[0].startswith("# ") and not lines[0].startswith("## "):
        return "\n".join(lines[1:])
    return markdown


def _build_prompt(context: dict) -> str:
    return (
        "Generate an evaluation report from the following experiment data. "
        "Base all claims on the data provided.\n\n"
        f"```json\n{json.dumps(context, default=str, indent=2)}\n```\n"
    )
