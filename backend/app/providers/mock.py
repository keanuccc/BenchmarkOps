"""Deterministic Mock provider.

Used when no OPENROUTER_API_KEY is configured, so the full evaluation pipeline is
runnable offline and in CI. Output is deterministic per (model_id, prompt) so tests
and demos are reproducible. It also tries to "answer" trivially by echoing the last
line / a heuristic, giving non-zero scores on simple exact-match benchmarks.
"""
from __future__ import annotations

import hashlib
import re

from app.providers.base import CompletionRequest, CompletionResult, LLMProvider


class MockProvider(LLMProvider):
    name = "mock"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        prompt = "\n".join(m.content for m in request.messages)

        answer = self._heuristic_answer(prompt)

        # Deterministic pseudo-token counts derived from content length.
        prompt_tokens = max(1, len(prompt) // 4)
        completion_tokens = max(1, len(answer) // 4)
        # Deterministic pseudo-latency in [50, 350) ms from a stable hash.
        digest = hashlib.sha256(f"{request.model_id}:{prompt}".encode()).hexdigest()
        latency_ms = 50 + (int(digest[:6], 16) % 300)

        return CompletionResult(
            text=answer,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            raw={"provider": "mock", "model_id": request.model_id},
        )

    @staticmethod
    def _heuristic_answer(prompt: str) -> str:
        """Cheap heuristics so mock runs produce plausible, occasionally-correct output."""
        # Simple arithmetic like "2+2" -> "4"
        m = re.search(r"(\d+)\s*([+\-*/])\s*(\d+)", prompt)
        if m:
            a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
            try:
                val = {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else 0}[op]
                return str(int(val) if float(val).is_integer() else val)
            except Exception:
                pass
        # Capital-of pattern
        if "france" in prompt.lower():
            return "Paris"
        # Fallback: echo the last non-empty line, truncated.
        lines = [ln.strip() for ln in prompt.splitlines() if ln.strip()]
        return (lines[-1][:120] if lines else "mock response")
