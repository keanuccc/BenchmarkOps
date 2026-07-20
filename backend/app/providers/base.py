"""LLM provider abstraction.

The Evaluation Engine depends only on this interface, never on a concrete SDK.
Adding a new gateway (OpenAI direct, Anthropic direct, Qwen, ...) means writing a
new adapter and registering it — zero changes to the engine or services.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ProviderRateLimitedError(Exception):
    """Raised when the upstream model gateway stays rate-limited (HTTP 429) and the
    run should abort instead of spinning indefinitely.

    The OpenRouter provider tracks consecutive 429s across rows (the provider is a
    shared singleton); once the burst threshold is hit it raises this so the runner
    can fail fast. Carries a human-readable `message`.
    """

    # When True the 429 is a *quota exhausted* signal (e.g. free-tier daily quota
    # used up) rather than a transient throttle: the runner must NOT keep backing off
    # and retrying today, since no amount of waiting will free more quota.
    quota_exhausted: bool = False

    def __init__(self, message: str = "", *, quota_exhausted: bool = False):
        super().__init__(message)
        self.quota_exhausted = quota_exhausted


class ProviderQuotaExhaustedError(ProviderRateLimitedError):
    """Raised when the upstream reports the daily/monthly quota is exhausted.

    A subclass of ProviderRateLimitedError so existing runner handling still catches
    it as a rate-limit failure, but with `quota_exhausted=True` so the runner can tell
    the two apart (and avoid spinning on a condition that won't clear until quota
    resets).
    """

    def __init__(self, message: str = ""):
        super().__init__(message, quota_exhausted=True)


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class CompletionRequest:
    model_id: str
    messages: list[ChatMessage]
    temperature: float = 0.0
    max_tokens: int | None = None
    # Control-plane flag: True when this model is a free tier that must be throttled
    # via the provider's token bucket. Never sent to the upstream API.
    is_free: bool = False
    # Open-ended passthrough fields merged into the upstream request payload.
    extra: dict = field(default_factory=dict)


@dataclass
class CompletionResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    raw: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMProvider(ABC):
    """Interface every model gateway must implement."""

    name: str

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResult:
        """Run a single chat completion. Must raise on unrecoverable errors."""
        raise NotImplementedError
