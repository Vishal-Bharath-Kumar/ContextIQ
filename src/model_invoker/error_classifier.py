"""Retryable error classifier for LiteLLM exceptions (TASK-US020-02)."""

from __future__ import annotations

import asyncio
from enum import StrEnum

import litellm.exceptions as lx


class RetryableErrorCode(StrEnum):
    HTTP_5XX = "http_5xx"  # 500, 502, 503, 504
    RATE_LIMITED = "rate_limited"  # HTTP 429
    TIMEOUT = "timeout"  # asyncio.TimeoutError or LiteLLM Timeout


def classify_error(exc: BaseException) -> RetryableErrorCode | None:
    """Return RetryableErrorCode if the error warrants a fallback, else None.

    Non-retryable errors (auth, bad request, context window) surface immediately.
    This function never raises — classifier exceptions must not propagate to the invoker.
    """
    try:
        if isinstance(exc, asyncio.TimeoutError):
            return RetryableErrorCode.TIMEOUT
        if isinstance(exc, lx.Timeout):
            return RetryableErrorCode.TIMEOUT
        if isinstance(exc, lx.RateLimitError):
            return RetryableErrorCode.RATE_LIMITED
        if isinstance(exc, lx.APIError):
            status = getattr(exc, "status_code", None)
            if status is not None and 500 <= status <= 599:
                return RetryableErrorCode.HTTP_5XX
        # AuthenticationError, BadRequestError, ContextWindowExceededError — not retryable
        return None
    except Exception:  # noqa: BLE001
        return None


def extract_provider(model_id: str) -> str:
    """Extract provider prefix from a model ID.

    'anthropic/claude-3-haiku' → 'anthropic'
    'gpt-4o-mini'              → 'openai'  (LiteLLM default provider for bare model names)
    """
    if "/" in model_id:
        return model_id.split("/")[0]
    return "openai"
