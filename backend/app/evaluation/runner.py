"""Evaluation runner — orchestrates a single experiment run."""
from __future__ import annotations

import asyncio
import logging
import re
import time

from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import AsyncSessionLocal, with_retry_on_lock
from app.evaluation.cancellation import clear_cancelled, is_cancelled
from app.evaluation.errors import RetryableTaskError
from app.evaluation.experiment_metrics import metric_columns
from app.evaluation.metrics import (
    _call_metric,
    get_metric,
    has_metric_suite,
    MetricEvaluationError,
    normalize_metric_suite,
)
from app.models.benchmark import Benchmark
from app.models.dataset import Dataset
from app.models.experiment import ExperimentResult
from app.models.model import Model
from app.models.prompt import Prompt
from app.providers.base import ChatMessage, CompletionRequest, ProviderRateLimitedError
from app.providers.registry import get_provider
from app.repositories.dataset import DatasetRowRepository
from app.services.prompt_variables import render_template
from app.repositories.experiment import (
    ExperimentRepository,
    ExperimentResultRepository,
)
from app.evaluation.task_queue import _mark_experiment_cancelled
from app.evaluation.task_records import mark_done, mark_running

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500
_PROGRESS_EVERY = 50

_ANSWER_PREFIX_RE = re.compile(
    r"^(?:最\s*终\s*答\s*案[：:\s]*|答\s*案(?:\s*是)?[：:\s]*|回\s*答[：:\s]*|答\s*题?[：:\s]*|answer[s]?[：:]?\s*|final\s+answer\s*[：:]?\s*|结\s*论[：:\s]*)",
    flags=re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^[ \t]*```[ \t]*(\w*)[ \t]*$", re.MULTILINE)


async def _load_dataset_rows(
    dataset_id: str, offset: int, limit: int, version: int | None = None
):
    """Fetch one page of dataset rows on a fresh session (bounded memory)."""
    async with AsyncSessionLocal() as session:
        repo = DatasetRowRepository(session)
        return await repo.list_by_dataset(
            dataset_id, offset=offset, limit=limit, version=version
        )


async def _flush_results(
    experiment_id: str, rows: list[ExperimentResult]
) -> None:
    """Persist one result batch on an isolated session.

    Unlike best-effort progress updates, result rows are authoritative: a
    failure after retrying transient lock contention is raised as a terminal
    (non-retryable) error so the distributed queue never re-runs the whole
    experiment and double-bills provider calls.
    """

    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            repo = ExperimentResultRepository(session)
            await repo.bulk_create(rows)
            await session.commit()

    try:
        await with_retry_on_lock(_write)
    except Exception as exc:
        raise RuntimeError(
            f"failed to persist result batch for experiment {experiment_id}: {exc}"
        ) from exc


async def _clear_results(experiment_id: str) -> None:
    """Best-effort removal of incrementally-written result rows (cancel path)."""

    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            repo = ExperimentResultRepository(session)
            await repo.delete_by_experiment(experiment_id)
            await session.commit()

    try:
        await with_retry_on_lock(_write)
    except Exception:
        logger.exception("failed to clear results for experiment %s", experiment_id)


async def _clear_stale_results(experiment_id: str) -> None:
    """Delete rows left by an earlier run before a fresh run starts writing.

    Failures (after transient lock retries) propagate to the caller, which
    marks the run failed instead of leaving stale/mixed result rows.
    """

    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            repo = ExperimentResultRepository(session)
            await repo.delete_by_experiment(experiment_id)
            await session.commit()

    await with_retry_on_lock(_write)


async def _handle_cancelled(experiment_id: str) -> None:
    """Mark cancelled, drop partial rows, and close the task record."""
    await _mark_experiment_cancelled(experiment_id)
    await _clear_results(experiment_id)
    await mark_done(experiment_id, status="cancelled")


async def _check_cancelled_db(experiment_id: str) -> bool:
    """Best-effort cross-process cancellation check (progress cadence only)."""
    try:
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(experiment_id)
            return exp is not None and exp.status == "cancelled"
    except Exception:
        return False


def _first_value(d: dict | None) -> str:
    """Extract the answer string from an expected-row dict.

    Datasets may store the answer under different key names (``answer``, ``label``,
    ``output``, ``target``, ``ground_truth``). We check those explicitly before
    falling back to ``next(iter(...))``.

    Handles common shapes:

    * ``{"answer": "北京"}`` → ``"北京"``
    * ``{"answer": ["北京", "北京市"]}`` → ``"北京"`` (first valid element)
    * ``{"answer": {"text": "北京", "confidence": 0.9}}`` → ``"北京"``
    * ``{"answer": 42}`` → ``"42"``
    * ``{"result": "北京"}`` → ``"北京"`` (fallback to first value)
    * ``None`` / empty → ``""``
    """
    if not d:
        return ""

    def _flatten(value: object) -> str:
        """Recursively extract a string from nested dicts/lists."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            for item in value:
                s = _flatten(item)
                if s:
                    return s
            return ""
        if isinstance(value, dict):
            # Prefer known answer keys, then first non-empty value.
            for key in ("answer", "label", "output", "target", "ground_truth", "value", "text"):
                if key in value:
                    s = _flatten(value[key])
                    if s:
                        return s
            for v in value.values():
                s = _flatten(v)
                if s:
                    return s
            return ""
        return str(value).strip()

    # First pass: look for known answer keys at the top level.
    for key in ("answer", "label", "output", "target", "ground_truth", "value", "text"):
        if key in d:
            result = _flatten(d[key])
            if result:
                return result

    # Fallback: flatten the first value.
    val = next(iter(d.values()), "")
    result = _flatten(val)
    return "" if not result else result


def _estimate_tokens(text: str) -> int:
    """Rough token estimate used for context-window pre-checks.

    CJK characters cost roughly one token each; other scripts average around
    4 chars per token. This deliberately errs toward *over*-estimating so we
    fail a row before the upstream rejects it with 400.
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + max(0, (other + 3) // 4)


def _extract_answer(
    text: str,
    *,
    split_commas: bool = True,
    normalize_whitespace: bool = True,
    strip_units: bool = True,
) -> str:
    """Strip the model's formatting noise so the metric compares against the
    bare answer.

    Handles the common patterns produced by the current prompt template:

    * ``答案：亚洲`` / ``答案: 亚洲`` / ``答案: 亚洲`` / ``Answer: Asia``
    * ``最终答案：xxx`` / ``结论：xxx``
    * Multi-line CoT output — takes the last non-empty line and strips the
      prefix from it.
    * Trailing units / parentheticals that pollute exact-match scoring
      (e.g. ``31元``, ``40平方厘米``, ``碳（C）``).
    * Whitespace inside the answer (e.g. ``18 世纪`` -> ``18世纪``).
    * Comma-separated multi-answer lines (e.g. ``答案：40平方厘米，13厘米``):
      extracts the first numeric or short token before the comma, since the
      expected value usually targets a single answer.
    """
    if not text:
        return ""

    # Split into lines; take the last non-empty line.
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    last = next((line for line in reversed(lines) if _ANSWER_PREFIX_RE.match(line)), lines[-1])

    # Strip common answer-prefixes (case-insensitive, handles Chinese/English
    # colons including full-width ： and ：).
    last = _ANSWER_PREFIX_RE.sub("", last)

    # Remove surrounding quotes that some models add.
    last = last.strip().strip('"').strip("'").strip()

    # Drop a trailing parenthetical annotation (e.g. "碳（C）" -> "碳"),
    # but keep a parenthesized answer such as "(A)".
    if not re.fullmatch(r"[（(][^）)]*[）)]", last):
        last = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", last)
    if len(last) >= 2 and ((last[0], last[-1]) in (("(", ")"), ("（", "）"))):
        last = last[1:-1].strip()

    # If the answer contains a Chinese comma suggesting multiple values were
    # given, take only the first segment. This handles cases like
    # "40平方厘米，13厘米" -> "40平方厘米" where the expected answer is just
    # the first value "40".
    if split_commas:
        if "，" in last:
            last = last.split("，", 1)[0].strip()
        elif "," in last and not re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", last):
            last = last.split(",", 1)[0].strip()

    # Strip leading labels like "面积=" / "半周长=" / "体积=" etc.
    last = re.sub(r"^(?:面积|周长|半周长|体积|质量|速度|时间|长度|宽度|高度)[=：:\s]*", "", last)

    # Drop trailing Chinese currency / measurement units that the model often appends.
    # Order matters: match compound units (e.g. 平方千米, 立方米) before atomic units
    # (米, 厘米) to avoid partial stripping like "100立方" from "100立方厘米".
    if strip_units:
        last = re.sub(r"(?:元|块|美元|人民币|元/|$/)?$", "", last)
        last = re.sub(
            r"(?<=\d)\s*(?:平方千米|平方公里|平方米|平方厘米|平方毫米|"
            r"立方米|立方分米|立方厘米|立方毫米|"
            r"公顷|千米|公里|米|厘米|毫米|"
            r"毫升|升|千克|克|吨|秒|分钟|小时|天|年|万元|亿元|个|只|头|条|张|本|辆|架|"
            r"倍|分|度|℃|°C|°F|kg|g|mg|ml|L|m|cm|mm|km)$",
            "",
            last,
        )

    # Strip trailing punctuation that snuck into the answer.
    last = last.rstrip("。,.!?！，、；：")

    # Normalize whitespace inside the answer so "18 世纪" matches "18世纪".
    last = re.sub(r"\s+", "" if normalize_whitespace else " ", last).strip()

    return last


def _extract_code(text: str) -> str:
    """Extract runnable code from a model output for coding benchmarks.

    Real models often wrap code in Markdown fences (`````python ... `````), which
    breaks code_pass execution. This helper:

    * if fenced blocks exist, concatenates their contents (most models emit one);
    * otherwise returns the raw text with any stray fence markers stripped.

    It deliberately skips the QA-oriented ``_extract_answer`` noise removal,
    which would truncate code at commas or keep only the last line.
    """
    if not text:
        return ""
    matches = list(_FENCE_RE.finditer(text))
    if not matches:
        return text.replace("```", "").strip()
    parts: list[str] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        parts.append(text[start:end].strip())
    return "\n\n".join(p for p in parts if p).strip() or text.strip()


def _score_reason(
    metric_name: str,
    score: float,
    cleaned_prediction: str,
    expected_canonical: str,
    metric_scores: dict[str, float] | None = None,
) -> str:
    outcome = "matched" if score >= 1.0 else "did not match"
    if metric_scores:
        components = ", ".join(
            f"{name}={value:.4f}" for name, value in metric_scores.items()
        )
        detail = f"weighted metric components: {components}"
    elif metric_name in ("contains", "agent"):
        detail = "expected substring matched as a standalone text span"
    elif metric_name == "numeric_match":
        detail = "first numeric values matched within tolerance"
    elif metric_name in ("fuzzy_match", "fuzzy_match_ci"):
        detail = "normalized Levenshtein similarity met the configured threshold"
    elif metric_name == "llm_judge":
        detail = "LLM judge classified the prediction as semantically equivalent"
    elif cleaned_prediction == expected_canonical:
        detail = "cleaned prediction equals expected canonical answer"
    else:
        detail = (
            f"cleaned prediction {cleaned_prediction!r} vs expected "
            f"{expected_canonical!r}"
        )
    return f"{metric_name}: {outcome}; {detail}"


def _render_prompt(template: str, variables: list[str], row_input: dict) -> str:
    ctx = {k: ("" if v is None else v) for k, v in row_input.items()}
    for var in variables:
        ctx.setdefault(var, "")
    try:
        return render_template(template, ctx)
    except (KeyError, IndexError):
        joined = "\n".join(f"{k}: {v}" for k, v in row_input.items())
        return f"{template}\n\n{joined}"


_CHAT_ROLES = ("system", "user", "assistant")
_EXPECTED_ANSWER_KEYS = ("answer", "expected", "label", "output", "target", "ground_truth")
_STRUCTURED_KEYS = ("messages", "examples")


def _render_examples(examples: list) -> str:
    """Render few-shot examples as Q/A blocks (strings pass through verbatim)."""
    blocks: list[str] = []
    for item in examples:
        if isinstance(item, str):
            blocks.append(item)
        elif isinstance(item, dict) and item:
            answer_keys = [key for key in _EXPECTED_ANSWER_KEYS if key in item]
            if answer_keys:
                answer_key = answer_keys[0]
                question_lines = [f"Q: {item[k]}" for k in item if k != answer_key]
                blocks.append("\n".join(question_lines + [f"A: {item[answer_key]}"]))
            else:
                blocks.append("\n".join(f"Q: {v}" for v in item.values()))
        else:
            raise ValueError(f"invalid example: {item!r}")
    return "\n\n".join(blocks)


def _build_messages(
    template: str,
    variables: list[str],
    row_input: dict,
    *,
    structured_chat: bool,
) -> list[ChatMessage]:
    """Assemble the chat message chain for one dataset row.

    With structured chat enabled, ``messages`` becomes the conversation history
    and ``examples`` is rendered into the final user turn. Without it the row is
    rendered exactly as before (single user message).
    """
    if not structured_chat:
        return [ChatMessage(role="user", content=_render_prompt(template, variables, row_input))]

    history: list[ChatMessage] = []
    messages = row_input.get("messages")
    if messages is not None:
        if not isinstance(messages, list):
            raise ValueError("'messages' must be a list of {role, content} objects")
        for i, item in enumerate(messages):
            valid = (
                isinstance(item, dict)
                and item.get("role") in _CHAT_ROLES
                and isinstance(item.get("content"), str)
            )
            if not valid:
                raise ValueError(
                    f"messages[{i}] must be {{role: system|user|assistant, content: str}}"
                )
            history.append(ChatMessage(role=item["role"], content=item["content"]))

    ctx = {k: v for k, v in row_input.items() if k not in _STRUCTURED_KEYS}
    few_shot = ""
    examples = row_input.get("examples")
    if examples is not None:
        if not isinstance(examples, list):
            raise ValueError("'examples' must be a list")
        few_shot = _render_examples(examples)
    rendered = _render_prompt(template, variables, ctx)
    final_text = f"{few_shot}\n\n{rendered}".strip() if few_shot else rendered
    history.append(ChatMessage(role="user", content=final_text))
    return history


def _cost(pricing: dict, prompt_tokens: int, completion_tokens: int) -> float:
    """Compute cost from per-1k pricing. Returns 0.0 when no pricing info is available."""
    try:
        if not pricing:
            return 0.0
        inp = float(pricing.get("input_per_1k", 0.0)) * (prompt_tokens / 1000.0)
        out = float(pricing.get("output_per_1k", 0.0)) * (completion_tokens / 1000.0)
        return round(inp + out, 6)
    except Exception:
        return 0.0


async def _mark_failed(experiment_id: str, error: str) -> None:
    """Write a terminal 'failed' status on an isolated short session.

    Must never be called on a session that is holding a transaction across a
    network await — this is its own connection so it doesn't contend with a
    long-running run. The write is retried on transient 'database is locked'
    contention; if it still fails after exhausting retries, the error is logged.
    """

    async def _write_failed() -> None:
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(experiment_id)
            if exp is not None:
                await repo.update(exp, {"status": "failed", "error": error[:500]})
                await session.commit()

    try:
        await with_retry_on_lock(_write_failed)
    except Exception:  # noqa: BLE001
        logger.exception("failed to persist terminal 'failed' status")


async def _persist_progress(
    experiment_id: str,
    processed: int,
    rows_total: int,
    *,
    cells_done: int = 0,
    cells_error: int = 0,
    metrics_update: dict | None = None,
) -> None:
    """Best-effort progress update on an isolated short session.

    The write is retried on transient 'database is locked' contention; since
    progress is best-effort, a final failure (retries exhausted) is only logged,
    never raised — matching the original no-throw semantics.
    """

    async def _write_progress() -> None:
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(experiment_id)
            if exp is not None and exp.status == "running":
                update = {
                    "progress": processed,
                    "rows_total": rows_total,
                    "cells_done": cells_done,
                    "cells_error": cells_error,
                }
                if metrics_update:
                    current_metrics = dict(exp.metrics or {})
                    current_metrics.update(metrics_update)
                    update["metrics"] = current_metrics
                    # Keep materialized columns in sync with the JSON blob so
                    # the dashboard / SSE show live values during the run.
                    update.update(metric_columns(current_metrics))
                await repo.update(
                    exp,
                    update,
                )
                await session.commit()

    try:
        await with_retry_on_lock(_write_progress)
    except Exception:  # noqa: BLE001
        logger.debug("progress update skipped (lock or missing experiment)")


async def run_experiment(experiment_id: str) -> None:
    """Run an experiment, converting transient pre-billing DB failures into a
    retryable marker for the distributed queue (ARQ retries those, and only
    those; provider-side failures stay terminal)."""
    try:
        await _run_experiment(experiment_id)
    except OperationalError as exc:
        if "database is locked" in str(exc):
            raise RetryableTaskError(
                f"transient database lock while claiming experiment {experiment_id}: {exc}"
            ) from exc
        raise


async def _run_experiment(experiment_id: str) -> None:
    logger.info("experiment %s run started", experiment_id)

    async with AsyncSessionLocal() as load_session:
        exp_repo = ExperimentRepository(load_session)
        experiment = await exp_repo.get(experiment_id)
        if experiment is None:
            return
        if experiment.status == "cancelled":
            logger.info(
                "experiment %s was cancelled; skipping queued run", experiment_id
            )
            await mark_done(experiment_id, status="cancelled")
            return
        if is_cancelled(experiment_id):
            logger.info(
                "experiment %s was cancelled in-process; skipping queued run",
                experiment_id,
            )
            await mark_done(experiment_id, status="cancelled")
            return

        if not await exp_repo.set_running_if_not_running(experiment_id):
            return
        # A fresh run now owns the experiment: drop stale cancellation markers
        # and any rows left behind by an earlier run.
        clear_cancelled(experiment_id)
        await load_session.commit()
        await mark_running(experiment_id)
        try:
            await _clear_stale_results(experiment_id)
        except Exception as exc:
            await _mark_failed(experiment_id, str(exc)[:500])
            await mark_done(experiment_id, status="failed", error=str(exc)[:500])
            return

        snap = experiment.prompt_snapshot
        if snap:
            template = snap.get("template", "")
            variables = snap.get("variables", []) or []
            prompt_version = snap.get("version")
        else:
            prompt = await load_session.get(Prompt, experiment.prompt_id)
            if prompt is None:
                return await _mark_failed(experiment_id, "Experiment references a missing prompt")
            template = prompt.template
            variables = prompt.variables
            prompt_version = getattr(prompt, "version", None)

        bsnap = experiment.benchmark_snapshot
        if bsnap:
            metric_name = bsnap.get("metric")
            metric_config = bsnap.get("metric_config", {}) or {}
            benchmark_spec = bsnap.get("spec", {}) or {}
            benchmark_type = bsnap.get("type")
        else:
            benchmark = await load_session.get(Benchmark, experiment.benchmark_id)
            if benchmark is None:
                return await _mark_failed(experiment_id, "Experiment references a missing benchmark")
            metric_name = benchmark.metric
            metric_config = benchmark.metric_config
            benchmark_spec = {}
            benchmark_type = benchmark.type

        dsnap = experiment.dataset_snapshot
        if dsnap:
            answer_policy = dsnap.get("answer_policy", {}) or {}
            structured_chat = bool(dsnap.get("structured_chat", False))
        else:
            dataset = await load_session.get(Dataset, experiment.dataset_id)
            contract = dataset.contract if dataset is not None else {}
            answer_policy = (contract or {}).get("answer_policy", {}) or {}
            structured_chat = bool((contract or {}).get("structured_chat", False))

        msnap = experiment.model_snapshot
        if msnap:
            model_ref = msnap.get("model_id")
            pricing = msnap.get("pricing", {}) or {}
            # Routing: honor the model's pinned provider if present in the snapshot,
            # else fall back to the configured default provider.
            model_provider = msnap.get("provider") or settings.default_provider
            model_is_free = bool(msnap.get("is_free", False))
            context_length = msnap.get("context_length")
        else:
            model = await load_session.get(Model, experiment.model_id)
            if model is None:
                return await _mark_failed(experiment_id, "Experiment references a missing model")
            model_ref = model.model_id
            pricing = model.pricing
            model_provider = model.provider or settings.default_provider
            context_length = model.context_length
            # Model table has no is_free column; derive from the ":free" suffix
            # convention and, for Qiniu, the configured free-model set.
            model_is_free = (
                model.model_id.endswith(":free")
                or (model.provider == "qiniu" and model.model_id in settings.qiniu_free_set)
            )

        if not metric_name:
            return await _mark_failed(experiment_id, "Experiment has no scoring metric")

        row_repo = DatasetRowRepository(load_session)
        if experiment.dataset_version is not None:
            dataset_total = await row_repo.count_by_dataset_version(
                experiment.dataset_id, experiment.dataset_version
            )
        else:
            dataset_total = await row_repo.count_by_dataset(experiment.dataset_id)

        metric_suite = normalize_metric_suite(metric_name, metric_config, benchmark_spec)
        explicit_metric_suite = has_metric_suite(metric_config, benchmark_spec)
        metric_fns = {item["name"]: get_metric(item["name"]) for item in metric_suite}
        total_weight = sum(item["weight"] for item in metric_suite) or 1.0
        # Route by the model's pinned provider (falling back to the configured default).
        # The registry raises if the named gateway has no key configured.
        provider = get_provider(model_provider)
        params = experiment.params or {}
        temperature = float(params.get("temperature", 0.0))
        max_tokens = params.get("max_tokens")

    pending_results: list[ExperimentResult] = []
    total_score = 0.0
    total_cost = 0.0
    total_tokens = 0
    total_latency = 0
    scored = 0
    provider_errors = 0
    metric_errors = 0
    processed = 0
    cells_done = 0   # rows scored successfully (drives the progress bar's "scored" count)
    cells_error = 0   # rows whose provider call failed
    rate_limited = False
    rate_limited_msg = ""
    started = time.perf_counter()

    async def _process_row(row):
        """Run one dataset row: render prompt, call the provider, score, build the
        result object. Returns (ExperimentResult, is_rate_limited). Pure per-row work;
        callers merge the returned object into shared accumulators after gather so the
        concurrent phase never touches shared state across an await point."""
        try:
            messages = _build_messages(
                template, variables, row.input, structured_chat=structured_chat
            )
        except (TypeError, ValueError) as exc:
            res = ExperimentResult(
                experiment_id=experiment_id,
                row_idx=row.idx,
                input=row.input,
                expected=row.expected,
                output="",
                score=0.0,
                error=f"invalid_chat_structure: {exc}"[:500],
            )
            return res, False, {}, "provider"
        if context_length is not None:
            estimated_prompt = "\n".join(m.content for m in messages)
            estimated = _estimate_tokens(estimated_prompt) + int(max_tokens or 0)
            if estimated > context_length:
                res = ExperimentResult(
                    experiment_id=experiment_id,
                    row_idx=row.idx,
                    input=row.input,
                    expected=row.expected,
                    output="",
                    score=0.0,
                    error=(
                        f"context_overflow: estimated {estimated} tokens exceeds "
                        f"model context_length {context_length}"
                    ),
                )
                return res, False, {}, "provider"
        req = CompletionRequest(
            model_id=model_ref,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            is_free=model_is_free,
            extra=params.get("extra") or {},
        )
        expected_str = _first_value(row.expected)
        try:
            completion = await asyncio.wait_for(
                provider.complete(req),
                timeout=settings.eval_request_timeout,
            )
            # Clean both sides before scoring: expected may come from a dict key,
            # prediction may carry prompt-enforced prefixes like 「答案：」.
            cleaned_expected = expected_str.strip()
            multi_answer = answer_policy.get("multi_answer")
            # Comma-splitting is only safe for exact-match short answers; for
            # generation/contains metrics it would truncate long-form predictions
            # (e.g. summaries) at the first comma and deflate the score.
            split_commas = (
                metric_name in {"exact_match", "exact_match_ci", "numeric_match"}
                and multi_answer not in ("all", "set")
            )
            if benchmark_type == "coding":
                # 代码评测：保留完整可执行代码（含 Markdown 围栏内容），
                # 不做 QA 式答案抽取（会截断代码）。
                cleaned_prediction = _extract_code(completion.text)
            else:
                cleaned_prediction = _extract_answer(
                    completion.text,
                    split_commas=split_commas,
                    normalize_whitespace=False,
                    strip_units=answer_policy.get("strip_units", True),
                ).strip()

            metric_scores: dict[str, float] = {}
            weighted_score = 0.0
            for item in metric_suite:
                kwargs = dict(item["config"])
                kwargs.setdefault("benchmark_type", benchmark_type)
                kwargs.setdefault("model_id", model_ref)
                kwargs.setdefault("provider", model_provider)
                kwargs.setdefault("answer_policy", answer_policy)
                kwargs["raise_on_error"] = True
                try:
                    metric_score = float(
                        await _call_metric(
                            metric_fns[item["name"]],
                            cleaned_prediction,
                            cleaned_expected,
                            expected_raw=row.expected,
                            **kwargs,
                        )
                    )
                except MetricEvaluationError:
                    raise
                except Exception as exc:
                    raise MetricEvaluationError(
                        f"metric {item['name']!r} failed: {exc}", kind="metric"
                    ) from exc
                metric_scores[item["name"]] = metric_score
                weighted_score += metric_score * item["weight"]
            score = weighted_score / total_weight
            score_reason = _score_reason(
                metric_name,
                score,
                cleaned_prediction,
                cleaned_expected,
                metric_scores,
            )
            if cleaned_prediction == "":
                finish_reason = (completion.raw or {}).get("finish_reason")
                score_reason = (
                    f"{score_reason}; empty_prediction finish_reason={finish_reason}"
                )

            cost = _cost(pricing or {}, completion.prompt_tokens, completion.completion_tokens)
            res = ExperimentResult(
                experiment_id=experiment_id,
                row_idx=row.idx,
                input=row.input,
                expected=row.expected,
                output=completion.text,
                score=score,
                cleaned_prediction=cleaned_prediction,
                expected_canonical=cleaned_expected,
                score_reason=score_reason,
                latency_ms=completion.latency_ms,
                tokens=completion.total_tokens,
                cost=cost,
            )
            return res, False, metric_scores, None
        except ProviderRateLimitedError as exc:
            res = ExperimentResult(
                experiment_id=experiment_id,
                row_idx=row.idx,
                input=row.input,
                expected=row.expected,
                output="",
                score=0.0,
                error=str(exc)[:500],
            )
            return res, True, {}, "provider"
        except MetricEvaluationError as exc:
            res = ExperimentResult(
                experiment_id=experiment_id,
                row_idx=row.idx,
                input=row.input,
                expected=row.expected,
                output=completion.text,
                score=0.0,
                error=f"metric_error[{exc.kind}]: {exc}"[:500],
            )
            return res, False, {}, exc.kind
        except Exception as exc:
            res = ExperimentResult(
                experiment_id=experiment_id,
                row_idx=row.idx,
                input=row.input,
                expected=row.expected,
                output="",
                score=0.0,
                error=str(exc)[:500],
            )
            return res, False, {}, "provider"

    metric_totals: dict[str, float] = {item["name"]: 0.0 for item in metric_suite}

    def _merge(res, is_rate_limited, metric_scores, error_kind):
        """Fold one processed row into the shared accumulators. Called after gather, so
        no two merges run concurrently — safe without extra locking."""
        nonlocal scored, cells_done, cells_error, provider_errors, metric_errors, total_score, total_cost
        nonlocal total_tokens, total_latency, rate_limited, rate_limited_msg
        pending_results.append(res)
        if is_rate_limited:
            provider_errors += 1
            cells_error += 1
            rate_limited = True
            rate_limited_msg = (res.error or "")[:500]
        else:
            # A successful completion vs a non-429 failure is distinguished by score/error.
            if res.error:
                if error_kind == "metric":
                    metric_errors += 1
                else:
                    provider_errors += 1
                cells_error += 1
            else:
                total_score += res.score or 0.0
                total_cost += res.cost or 0.0
                total_tokens += res.tokens or 0
                total_latency += res.latency_ms or 0
                for name, metric_score in metric_scores.items():
                    metric_totals[name] = metric_totals.get(name, 0.0) + metric_score
                scored += 1
                cells_done += 1

    def _progress_metrics() -> dict:
        """Live metrics for the running experiment (drives the UI's ETA)."""
        runtime_now = time.perf_counter() - started
        avg_ms = (runtime_now * 1000 / scored) if scored else None
        metrics: dict = {}
        if avg_ms is not None:
            metrics["avg_ms_per_row"] = round(avg_ms, 1)
        if scored:
            metrics["accuracy"] = round(total_score / scored, 4)
        return metrics

    is_free = model_is_free

    async def _flush_if_due() -> None:
        """Persist the current result batch once it reaches the configured size."""
        if len(pending_results) >= settings.eval_result_batch_size:
            await _flush_results(experiment_id, pending_results)
            pending_results.clear()

    try:
        if is_free:
            # Free models measured RPM>=325 + high burst; run rows concurrently (bounded by
            # free_model_concurrency) and merge results serially. No fixed per-row sleep.
            # Applies to OpenRouter ":free" models and Qiniu free-tier models alike, since
            # the provider layer throttles them via its own token bucket.
            sem = asyncio.Semaphore(settings.free_model_concurrency)

            async def _guarded(row):
                async with sem:
                    return await _process_row(row)

            offset = 0
            while True:
                db_batch = await _load_dataset_rows(
                    experiment.dataset_id,
                    offset=offset,
                    limit=_BATCH_SIZE,
                    version=experiment.dataset_version,
                )
                if not db_batch:
                    break
                offset += len(db_batch)
                for i in range(0, len(db_batch), settings.free_model_concurrency):
                    batch = db_batch[i : i + settings.free_model_concurrency]
                    outcomes = await asyncio.gather(*(_guarded(r) for r in batch))
                    for res, is_rl, metric_scores, error_kind in outcomes:
                        _merge(res, is_rl, metric_scores, error_kind)
                    processed += len(batch)
                    await _flush_if_due()
                    # Report progress per batch (batch size == free_model_concurrency,
                    # well under _PROGRESS_EVERY), so the UI bar advances without
                    # waiting for a full _PROGRESS_EVERY worth of rows.
                    await _persist_progress(
                        experiment_id,
                        processed,
                        dataset_total,
                        cells_done=cells_done,
                        cells_error=cells_error,
                        metrics_update=_progress_metrics(),
                    )
                    if rate_limited:
                        break
                    if is_cancelled(experiment_id):
                        await _handle_cancelled(experiment_id)
                        return
                    if processed % _PROGRESS_EVERY == 0 and await _check_cancelled_db(
                        experiment_id
                    ):
                        await _handle_cancelled(experiment_id)
                        return
                if rate_limited:
                    break
        else:
            # Non-free models: keep the original strict-serial behavior (rate safety is
            # handled by the task queue's eval_max_workers, not by in-run concurrency).
            offset = 0
            while True:
                db_batch = await _load_dataset_rows(
                    experiment.dataset_id,
                    offset=offset,
                    limit=_BATCH_SIZE,
                    version=experiment.dataset_version,
                )
                if not db_batch:
                    break
                offset += len(db_batch)
                for row in db_batch:
                    res, is_rl, metric_scores, error_kind = await _process_row(row)
                    _merge(res, is_rl, metric_scores, error_kind)
                    processed += 1
                    await _flush_if_due()
                    if processed % _PROGRESS_EVERY == 0:
                        await _persist_progress(
                            experiment_id,
                            processed,
                            dataset_total,
                            cells_done=cells_done,
                            cells_error=cells_error,
                            metrics_update=_progress_metrics(),
                        )
                        if await _check_cancelled_db(experiment_id):
                            await _handle_cancelled(experiment_id)
                            return
                    if rate_limited:
                        break
                    if is_cancelled(experiment_id):
                        await _handle_cancelled(experiment_id)
                        return
                if rate_limited:
                    break
    except Exception as exc:
        # A batch persist failure after provider calls started must be terminal
        # (never retryable — ARQ would otherwise re-run and double-bill).
        await _mark_failed(experiment_id, str(exc)[:500])
        await mark_done(experiment_id, status="failed", error=str(exc)[:500])
        return

    n = processed
    accuracy = (total_score / scored) if scored else 0.0
    avg_latency = (total_latency / scored) if scored else 0.0
    runtime_s = (time.perf_counter() - started) if scored > 0 else 0
    avg_ms_per_row = (runtime_s * 1000 / scored) if scored > 0 else 0
    status = "failed" if rate_limited else (
        "partial" if provider_errors + metric_errors > 0 else "completed"
    )
    metrics_by_name = {
        name: metric_total / scored
        for name, metric_total in metric_totals.items()
        if scored
    }
    cost_unknown = (
        not model_is_free
        and (
            not pricing
            or (
                "input_per_1k" not in pricing
                and "output_per_1k" not in pricing
            )
        )
    )
    metrics = {
        "metric": "metric_suite" if explicit_metric_suite else metric_name,
        "accuracy": round(accuracy, 4),
        "primary_score": round(accuracy, 4),
        "metrics_by_name": metrics_by_name,
        "avg_latency_ms": round(avg_latency, 1),
        "avg_ms_per_row": round(avg_ms_per_row, 1),
        "rows_total": n,
        "dataset_rows_total": dataset_total,
        "rows_scored": scored,
        "rows_failed": n - scored,
        "rows_unprocessed": max(dataset_total - processed, 0),
        "coverage": round(scored / dataset_total, 4) if dataset_total else 0.0,
        "failure_rate": round((provider_errors + metric_errors) / dataset_total, 4)
        if dataset_total
        else 0.0,
        "provider_errors": provider_errors,
        "metric_errors": metric_errors,
        "prompt_version": prompt_version,
        "cost_unknown": cost_unknown,
    }
    runtime_ms = int((time.perf_counter() - started) * 1000)

    async def _persist() -> None:
        async with AsyncSessionLocal() as session:
            exp_repo = ExperimentRepository(session)
            if not await exp_repo.finish_if_running(
                experiment_id, status=status, error=rate_limited_msg or None
            ):
                logger.info("experiment %s lost persist race; discarding", experiment_id)
                # Remove rows this run may have written incrementally; the
                # experiment now belongs to a newer state (e.g. cancelled).
                res_repo = ExperimentResultRepository(session)
                await res_repo.delete_by_experiment(experiment_id)
                await session.commit()
                return
            res_repo = ExperimentResultRepository(session)
            await res_repo.bulk_create(pending_results)
            exp = await exp_repo.get(experiment_id)
            await exp_repo.update(
                exp,
                {
                    "progress": processed,
                    "rows_total": n,
                    "cells_done": cells_done,
                    "cells_error": cells_error,
                    "metrics": metrics,
                    **metric_columns(metrics),
                    "total_cost": round(total_cost, 6),
                    "total_tokens": total_tokens,
                    "runtime_ms": runtime_ms,
                },
            )
            await session.commit()

    # The whole persist transaction is wrapped in a lock-retry so a transient
    # 'database is locked' (e.g. two backend processes sharing the SQLite file)
    # recovers instead of silently losing results. If retries are exhausted, we
    # surface the failure as a terminal 'failed' rather than leaving the
    # experiment stuck in 'running'.
    try:
        await with_retry_on_lock(_persist)
        await mark_done(
            experiment_id,
            status="succeeded" if status in ("completed", "partial") else "failed",
            error=rate_limited_msg or None,
        )
        # Fire-and-forget lifecycle webhooks; delivery failures are logged in
        # the webhook service and never affect the run outcome.
        try:
            from app.services.webhook_service import notify_experiment

            asyncio.create_task(
                notify_experiment(experiment_id, status),
                name=f"webhook-notify-{experiment_id}",
            )
        except Exception:  # noqa: BLE001
            logger.exception("webhook notify scheduling failed for %s", experiment_id)
    except Exception as exc:
        logger.exception("experiment %s persist failed", experiment_id)
        # Preserve the original diagnostic; a 'database is locked' failure is the
        # common case, but any other persist error (e.g. disk I/O) must keep its
        # own message so it stays debuggable in the UI.
        await _mark_failed(experiment_id, str(exc)[:500])
        await mark_done(experiment_id, status="failed", error=str(exc)[:500])
