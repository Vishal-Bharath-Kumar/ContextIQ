"""Tests for error_classifier module — 100% branch coverage (TASK-US020-02)."""

from __future__ import annotations

import unittest.mock as mock

import litellm.exceptions as lx
import pytest
from pydantic import ValidationError

import src.model_invoker.error_classifier as ec
from src.model_invoker.error_classifier import (
    RetryableErrorCode,
    classify_error,
    extract_provider,
)
from src.model_invoker.schemas.fallback_event import FallbackEvent

# ---------------------------------------------------------------------------
# classify_error — retryable paths
# ---------------------------------------------------------------------------


class TestClassifyErrorRetryable:
    def test_rate_limit_error_returns_rate_limited(self) -> None:
        exc = lx.RateLimitError(
            message="rate limited",
            llm_provider="openai",
            model="gpt-4o",
        )
        assert classify_error(exc) == RetryableErrorCode.RATE_LIMITED

    def test_api_error_5xx_returns_http_5xx(self) -> None:
        exc = lx.APIError(
            status_code=503,
            message="service unavailable",
            llm_provider="openai",
            model="gpt-4o",
        )
        assert classify_error(exc) == RetryableErrorCode.HTTP_5XX

    def test_api_error_500_returns_http_5xx(self) -> None:
        exc = lx.APIError(
            status_code=500,
            message="internal server error",
            llm_provider="openai",
            model="gpt-4o",
        )
        assert classify_error(exc) == RetryableErrorCode.HTTP_5XX

    def test_api_error_504_returns_http_5xx(self) -> None:
        exc = lx.APIError(
            status_code=504,
            message="gateway timeout",
            llm_provider="openai",
            model="gpt-4o",
        )
        assert classify_error(exc) == RetryableErrorCode.HTTP_5XX

    def test_asyncio_timeout_returns_timeout(self) -> None:
        assert classify_error(TimeoutError()) == RetryableErrorCode.TIMEOUT

    def test_litellm_timeout_returns_timeout(self) -> None:
        exc = lx.Timeout(
            message="timed out",
            model="gpt-4o",
            llm_provider="openai",
        )
        assert classify_error(exc) == RetryableErrorCode.TIMEOUT


# ---------------------------------------------------------------------------
# classify_error — non-retryable paths
# ---------------------------------------------------------------------------


class TestClassifyErrorNonRetryable:
    def test_authentication_error_returns_none(self) -> None:
        exc = lx.AuthenticationError(
            message="invalid api key",
            llm_provider="openai",
            model="gpt-4o",
        )
        assert classify_error(exc) is None

    def test_bad_request_error_returns_none(self) -> None:
        exc = lx.BadRequestError(
            message="bad request",
            model="gpt-4o",
            llm_provider="openai",
        )
        assert classify_error(exc) is None

    def test_context_window_exceeded_returns_none(self) -> None:
        exc = lx.ContextWindowExceededError(
            message="context window exceeded",
            model="gpt-4o",
            llm_provider="openai",
        )
        assert classify_error(exc) is None

    def test_api_error_4xx_returns_none(self) -> None:
        exc = lx.APIError(
            status_code=400,
            message="bad request",
            llm_provider="openai",
            model="gpt-4o",
        )
        assert classify_error(exc) is None

    def test_api_error_no_status_code_returns_none(self) -> None:
        exc = lx.APIError(
            status_code=200,
            message="unexpected",
            llm_provider="openai",
            model="gpt-4o",
        )
        # status_code 200 — not in 5xx range
        assert classify_error(exc) is None

    def test_generic_exception_returns_none(self) -> None:
        assert classify_error(ValueError("unexpected")) is None

    def test_runtime_error_returns_none(self) -> None:
        assert classify_error(RuntimeError("something")) is None

    def test_classifier_internal_error_returns_none(self) -> None:
        """Defensive guard: internal classifier failure must not propagate."""
        with mock.patch.object(ec.lx, "Timeout", side_effect=TypeError("patched")):
            result = ec.classify_error(object())  # type: ignore[arg-type]
        assert result is None


# ---------------------------------------------------------------------------
# extract_provider
# ---------------------------------------------------------------------------


class TestExtractProvider:
    def test_provider_with_slash(self) -> None:
        assert extract_provider("anthropic/claude-3-haiku") == "anthropic"

    def test_gpt_bare_model_name_defaults_to_openai(self) -> None:
        assert extract_provider("gpt-4o-mini") == "openai"

    def test_multi_segment_model_id_returns_first(self) -> None:
        assert extract_provider("azure/gpt-4o/deployment") == "azure"

    def test_bare_model_no_slash_returns_openai(self) -> None:
        assert extract_provider("claude-3-sonnet") == "openai"


# ---------------------------------------------------------------------------
# FallbackEvent construction
# ---------------------------------------------------------------------------


class TestFallbackEvent:
    def test_construct_with_fallback_model(self) -> None:
        event = FallbackEvent(
            attempt=1,
            primary_model_id="openai/gpt-4o",
            error_code=RetryableErrorCode.RATE_LIMITED,
            fallback_model_id="anthropic/claude-3-haiku",
            provider="openai",
        )
        assert event.attempt == 1
        assert event.primary_model_id == "openai/gpt-4o"
        assert event.error_code == RetryableErrorCode.RATE_LIMITED
        assert event.fallback_model_id == "anthropic/claude-3-haiku"
        assert event.provider == "openai"

    def test_construct_with_chain_exhausted(self) -> None:
        event = FallbackEvent(
            attempt=3,
            primary_model_id="anthropic/claude-3-haiku",
            error_code=RetryableErrorCode.HTTP_5XX,
            fallback_model_id=None,
            provider="anthropic",
        )
        assert event.fallback_model_id is None

    def test_frozen_model_raises_on_mutation(self) -> None:
        event = FallbackEvent(
            attempt=1,
            primary_model_id="openai/gpt-4o",
            error_code=RetryableErrorCode.TIMEOUT,
            fallback_model_id=None,
            provider="openai",
        )
        with pytest.raises(ValidationError):
            event.attempt = 2  # type: ignore[misc]

    def test_error_code_is_str_enum(self) -> None:
        assert RetryableErrorCode.HTTP_5XX == "http_5xx"
        assert RetryableErrorCode.RATE_LIMITED == "rate_limited"
        assert RetryableErrorCode.TIMEOUT == "timeout"
