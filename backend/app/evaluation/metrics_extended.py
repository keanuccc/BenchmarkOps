"""Extended metrics: code execution, semantic similarity, agent tool calls.

These live in a separate module so the core metric registry stays small and
the optional, heavier capabilities can be imported explicitly.

- ``code_pass``: runs the model output against per-row test cases in an
  isolated subprocess and scores the pass rate. Requires test code in the
  dataset row (``expected.tests``) or benchmark config (``tests``).
- ``semantic_similarity``: dependency-free lexical-semantic overlap using
  token F1 plus character bigram Jaccard.
- ``tool_call``: checks whether the model output contains the expected tool
  name (and, optionally, expected argument keys) in a JSON tool-call block.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from app.evaluation.metrics import register


# Modules blocked inside the code-execution sandbox. Model-generated code for
# coding benchmarks only needs plain standard-library algorithms; anything that
# touches the OS, network, or other processes is an escape risk and is rejected.
_BLOCKED_MODULES = frozenset(
    {
        "os",
        "subprocess",
        "sys",
        "socket",
        "shutil",
        "importlib",
        "ctypes",
        "pickle",
        "marshal",
        "pathlib",
        "builtins",
        "io",
        "multiprocessing",
        "threading",
        "concurrent",
        "requests",
        "httpx",
        "urllib",
    }
)

_GUARD_PREAMBLE = (
    "import builtins as _bmops_builtins\n"
    "_bmops_real_import = _bmops_builtins.__import__\n"
    f"_BM_OPS_BLOCKED = {sorted(_BLOCKED_MODULES)!r}\n"
    "_bmops_importing = False\n"
    "def _bmops_import(name, *args, **kwargs):\n"
    "    global _bmops_importing\n"
    "    if not _bmops_importing:\n"
    "        if name.split('.')[0] in _BM_OPS_BLOCKED:\n"
    "            raise ImportError('module blocked in evaluation sandbox: ' + name)\n"
    "        _bmops_importing = True\n"
    "        try:\n"
    "            return _bmops_real_import(name, *args, **kwargs)\n"
    "        finally:\n"
    "            _bmops_importing = False\n"
    "    return _bmops_real_import(name, *args, **kwargs)\n"
    "_bmops_builtins.__import__ = _bmops_import\n"
)


def _extract_tests(expected_raw: dict | list | None, kwargs: dict) -> list[str]:
    """Pull test-case code from the row's expected payload or metric config."""
    tests: list[str] = []
    if isinstance(expected_raw, dict):
        raw = expected_raw.get("tests")
        if isinstance(raw, list):
            tests = [str(t) for t in raw if str(t).strip()]
        elif isinstance(raw, str) and raw.strip():
            tests = [raw]
    config_tests = kwargs.get("tests")
    if isinstance(config_tests, list):
        tests.extend(str(t) for t in config_tests if str(t).strip())
    return tests


async def _run_python(code: str, test: str, timeout: float, *, sandbox: bool = True) -> bool:
    """Run one test snippet against the model output in a fresh interpreter.

    With ``sandbox`` enabled (the default), a guard preamble is prepended that
    blocks imports of dangerous modules and the interpreter is started with
    ``-I`` (isolated mode) so user site-packages and environment variables are
    ignored. This is a best-effort local sandbox, not a container boundary.
    """
    preamble = _GUARD_PREAMBLE if sandbox else ""
    script = f"{preamble}\n{code}\n\n{test}\n"

    def _run() -> int:
        with tempfile.TemporaryDirectory(prefix="bmops_code_") as tmp:
            path = Path(tmp) / "solution.py"
            path.write_text(script, encoding="utf-8")
            try:
                argv = [sys.executable]
                if sandbox:
                    argv.append("-I")
                argv.append(str(path))
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    timeout=timeout,
                    cwd=tmp,
                )
                return proc.returncode
            except subprocess.TimeoutExpired:
                return 124
            except OSError:
                return 125

    return await asyncio.to_thread(_run) == 0


@register("code_pass")
async def code_pass(
    prediction: str,
    expected: str | None,
    *,
    expected_raw: dict | list | None = None,
    **kwargs,
) -> float:
    """Score the fraction of test cases the model output passes.

    Test cases come from ``expected.tests`` (per row) or ``tests`` in the
    metric config. The model output is prepended to each test and executed in
    a subprocess with a per-case timeout (default 5s, configurable via
    ``timeout_seconds``). No tests available -> 0 (unverifiable).
    """
    tests = _extract_tests(expected_raw, kwargs)
    if not tests:
        return 0.0
    code = (prediction or "").strip()
    if not code:
        return 0.0
    timeout = float(kwargs.get("timeout_seconds", 5) or 5)
    sandbox = bool(kwargs.get("sandbox", True))
    results = await asyncio.gather(
        *(_run_python(code, test, timeout, sandbox=sandbox) for test in tests)
    )
    return sum(results) / len(results)


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,.;:!?()\[\]{}\"'=+-]+", text.lower()) if t]


def _bigrams(text: str) -> Counter:
    compact = re.sub(r"\s+", "", text.lower())
    return Counter(compact[i : i + 2] for i in range(max(len(compact) - 1, 0)))


def _f1(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    ca, cb = Counter(a), Counter(b)
    overlap = sum((ca & cb).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(a)
    recall = overlap / len(b)
    return 2 * precision * recall / (precision + recall)


def _jaccard(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    inter = sum((a & b).values())
    union = sum((a | b).values())
    return inter / union if union else 0.0


def _normalize_for_similarity(text: str) -> str:
    """Lowercase and collapse digits/punctuation for character-level matching."""
    normalized = re.sub(r"\d", "#", text.lower())
    normalized = re.sub(r"[\s，。！？、；：,.!?;:'\"()\[\]{}<>《》【】]", "", normalized)
    return normalized


@register("semantic_similarity")
def semantic_similarity(
    prediction: str,
    expected: str | None,
    *,
    expected_raw: dict | list | None = None,
    **kwargs,
) -> float:
    """Lexical-semantic overlap without external embedding APIs.

    Blends character-level SequenceMatcher similarity (default weight 0.9)
    with token F1 (0.1). Digits are normalized so "1-3" and "一" differ only
    through their characters. Weights are tunable via ``text_weight`` in the
    metric config.
    """
    expected_text = expected or ""
    if not expected_text.strip() or not (prediction or "").strip():
        return 0.0
    text_weight = float(kwargs.get("text_weight", 0.9) or 0.9)
    text_sim = SequenceMatcher(
        None,
        _normalize_for_similarity(prediction),
        _normalize_for_similarity(expected_text),
    ).ratio()
    f1 = _f1(_tokenize(prediction), _tokenize(expected_text))
    return text_weight * text_sim + (1 - text_weight) * f1


_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(.*?)```|(\{[^{}]*\"(?:name|function|tool)\"[^{}]*\})",
    re.IGNORECASE | re.DOTALL,
)


def _extract_tool_calls(prediction: str) -> list[dict]:
    calls: list[dict] = []
    # 1) The whole output may already be a JSON object / array.
    try:
        data = json.loads(prediction.strip())
        if isinstance(data, dict):
            calls.append(data)
        elif isinstance(data, list):
            calls.extend(d for d in data if isinstance(d, dict))
    except json.JSONDecodeError:
        pass
    # 2) Fenced JSON blocks (```json ... ```).
    for block in _JSON_BLOCK_RE.findall(prediction):
        raw = block[0] or block[1]
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            data = next((d for d in data if isinstance(d, dict)), None)
        if isinstance(data, dict):
            calls.append(data)
    # 3) Best-effort substring extraction: first '{' .. last '}'.
    if not calls:
        start = prediction.find("{")
        end = prediction.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(prediction[start : end + 1])
                if isinstance(data, dict):
                    calls.append(data)
            except json.JSONDecodeError:
                pass
    return calls


def _tool_name(call: dict) -> str:
    for key in ("name", "tool", "tool_name"):
        value = call.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    function = call.get("function")
    if isinstance(function, dict):
        value = function.get("name")
        if isinstance(value, str):
            return value
    return ""


def _tool_arguments(call: dict) -> dict:
    for key in ("arguments", "parameters", "input"):
        value = call.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
    return {}


@register("tool_call")
def tool_call(
    prediction: str,
    expected: str | None,
    *,
    expected_raw: dict | list | None = None,
    **kwargs,
) -> float:
    """Agent tool-call check: expected tool name and optional argument keys.

    ``expected`` is the tool name; ``expected.arguments`` (dict) lists the
    argument keys that must be present. A matching tool with all required
    argument keys scores 1.0; a matching tool with missing arguments scores
    0.5; no matching tool scores 0.
    """
    calls = _extract_tool_calls(prediction or "")
    if not calls:
        return 0.0
    expected_name = (expected or "").strip()
    if not expected_name:
        return 0.0
    required_keys = []
    if isinstance(expected_raw, dict):
        args = expected_raw.get("arguments")
        if isinstance(args, dict):
            required_keys = list(args.keys())
    for call in calls:
        if _tool_name(call) != expected_name:
            continue
        arguments = _tool_arguments(call)
        if not required_keys:
            return 1.0
        if all(key in arguments for key in required_keys):
            return 1.0
        return 0.5
    return 0.0
