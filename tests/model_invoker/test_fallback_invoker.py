"""Tests for FallbackInvoker (TASK-US020-04)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import litellm.exceptions as lx
import pytest

from src.model_invoker.circuit_breaker import ProviderCircuitBreaker
from src.model_invoker.config import InvokerSettings
from src.model_invoker.error_classifier import RetryableErrorCode
from src.model_invoker.fallback_invoker import FallbackInvoker
from src.model_invoker.invoker import LiteLLMInvoker
from src.model_invoker.schemas.fallback_chain import FallbackChain, InvocationFailure
from src.model_invoker.schemas.llm_response import LLMResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MESSAGES = [{"role": "user", "content": "Hello"}]
TOKEN_BUDGET = 256

CHAIN_2 = FallbackChain(
    model_ids=["openai/gpt-4o-mini", "anthropic/claude-3-haiku"],
    intent_type="chat",
)
CHAIN_3 = FallbackChain(
    model_ids=["openai/gpt-4o-mini", "anthropic/claude-3-haiku", "openai/gpt-3.5-turbo"],
    intent_type="chat",
)
CHAIN_4 = FallbackChain(
    model_ids=[
        "openai/gpt-4o-mini",
        "anthropic/claude-3-haiku",
        "openai/gpt-3.5-turbo",
        "mistral/mistral-small",
    ],
    intent_type="chat",
)


def _make_response(model_id: str = "openai/gpt-4o-mini") -> LLMResponse:
    return LLMResponse(
        model_id=model_id,
        content="OK",
        input_tokens=10,
        output_tokens=5,
        finish_reason="stop",
    )


def _make_invoker_with_circuit_breaker(
    max_fallback_attempts: int = 3,
) -> tuple[AsyncMock, AsyncMock, FallbackInvoker]:
    """Return (mock_invoker, mock_circuit_breaker, fallback_invoker)."""
    mock_invoker = AsyncMock(spec=LiteLLMInvoker)
    mock_cb = AsyncMock(spec=ProviderCircuitBreaker)
    mock_cb.is_available.return_value = True  # default: circuit CLOSED
    mock_cb.record_success = AsyncMock()
    mock_cb.record_failure = AsyncMock()

    settings = InvokerSettings(max_fallback_attempts=max_fallback_attempts)
    fi = FallbackInvoker(invoker=mock_invoker, circuit_breaker=mock_cb, settings=settings)
    return mock_invoker, mock_cb, fi


# ---------------------------------------------------------------------------
# Success path tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_on_first_attempt() -> None:
    """Primary model succeeds → LLMResponse returned, record_success called."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker()
    expected = _make_response("openai/gpt-4o-mini")
    mock_invoker.invoke.return_value = expected

    result = await fi.invoke(CHAIN_2, MESSAGES, TOKEN_BUDGET)

    assert result == expected
    mock_invoker.invoke.assert_called_once()
    mock_cb.record_success.assert_called_once_with("openai")
    mock_cb.record_failure.assert_not_called()


@pytest.mark.asyncio
async def test_success_on_second_attempt() -> None:
    """Primary fails with retryable error; second model succeeds."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker()
    expected = _make_response("anthropic/claude-3-haiku")

    # First call raises rate-limit; second call succeeds
    mock_invoker.invoke.side_effect = [
        lx.RateLimitError("rate limited", llm_provider="openai", model="gpt-4o-mini"),
        expected,
    ]

    result = await fi.invoke(CHAIN_2, MESSAGES, TOKEN_BUDGET)

    assert result == expected
    assert mock_invoker.invoke.call_count == 2
    mock_cb.record_failure.assert_called_once_with("openai")
    mock_cb.record_success.assert_called_once_with("anthropic")


@pytest.mark.asyncio
async def test_record_success_called_after_successful_invocation() -> None:
    """Ensure record_success is called with the correct provider on success."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker()
    mock_invoker.invoke.return_value = _make_response("anthropic/claude-3-haiku")

    chain = FallbackChain(model_ids=["anthropic/claude-3-haiku"], intent_type="chat")
    await fi.invoke(chain, MESSAGES, TOKEN_BUDGET)

    mock_cb.record_success.assert_called_once_with("anthropic")


# ---------------------------------------------------------------------------
# Exhaustion → InvocationFailure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_models_exhausted_returns_invocation_failure() -> None:
    """All candidates fail → InvocationFailure with correct attempts count."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker(max_fallback_attempts=3)

    mock_invoker.invoke.side_effect = lx.RateLimitError(
        "rate limited", llm_provider="openai", model="any"
    )

    result = await fi.invoke(CHAIN_4, MESSAGES, TOKEN_BUDGET)

    assert isinstance(result, InvocationFailure)
    assert result.attempts == 4
    assert result.last_error_code == RetryableErrorCode.RATE_LIMITED.value
    assert result.tried_model_ids == list(CHAIN_4.model_ids)


@pytest.mark.asyncio
async def test_invocation_failure_message_contains_count() -> None:
    """InvocationFailure.message mentions the number of models tried."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker(max_fallback_attempts=1)

    mock_invoker.invoke.side_effect = TimeoutError()

    result = await fi.invoke(CHAIN_2, MESSAGES, TOKEN_BUDGET)

    assert isinstance(result, InvocationFailure)
    assert "2" in result.message
    assert result.last_error_code == RetryableErrorCode.TIMEOUT.value


@pytest.mark.asyncio
async def test_max_fallback_attempts_caps_total_calls() -> None:
    """FallbackInvoker never exceeds max_fallback_attempts + 1 LiteLLM calls."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker(max_fallback_attempts=2)

    mock_invoker.invoke.side_effect = lx.RateLimitError(
        "rate limited", llm_provider="openai", model="any"
    )

    result = await fi.invoke(CHAIN_4, MESSAGES, TOKEN_BUDGET)

    assert isinstance(result, InvocationFailure)
    # max_fallback_attempts=2 → primary + 2 fallbacks → 3 total
    assert mock_invoker.invoke.call_count == 3
    assert result.attempts == 3


# ---------------------------------------------------------------------------
# Circuit breaker integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_circuit_is_skipped_no_invoke_call() -> None:
    """Model with open circuit is skipped; LiteLLMInvoker.invoke() not called for it."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker()

    # First provider (openai) circuit is OPEN; second (anthropic) is CLOSED
    async def _is_available(provider: str) -> bool:
        return provider != "openai"

    mock_cb.is_available.side_effect = _is_available
    expected = _make_response("anthropic/claude-3-haiku")
    mock_invoker.invoke.return_value = expected

    result = await fi.invoke(CHAIN_2, MESSAGES, TOKEN_BUDGET)

    assert result == expected
    # invoke() should only have been called for anthropic, not openai
    call_kwargs = mock_invoker.invoke.call_args_list
    assert all("anthropic" in kw.kwargs.get("model_id", "") for kw in call_kwargs)
    mock_invoker.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_open_circuit_model_added_to_tried() -> None:
    """Skipped (open circuit) model IDs are counted in tried to conserve fallback budget."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker(max_fallback_attempts=1)

    # All circuits open
    mock_cb.is_available.return_value = False

    result = await fi.invoke(CHAIN_2, MESSAGES, TOKEN_BUDGET)

    assert isinstance(result, InvocationFailure)
    # Both model IDs should appear in tried even though invoke was never called
    assert set(result.tried_model_ids) == set(CHAIN_2.model_ids)
    mock_invoker.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_record_failure_called_on_retryable_error() -> None:
    """record_failure is called with the correct provider after a retryable error."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker()

    mock_invoker.invoke.side_effect = [
        lx.RateLimitError("rate limited", llm_provider="openai", model="gpt-4o-mini"),
        _make_response("anthropic/claude-3-haiku"),
    ]

    await fi.invoke(CHAIN_2, MESSAGES, TOKEN_BUDGET)

    mock_cb.record_failure.assert_called_once_with("openai")


# ---------------------------------------------------------------------------
# Non-retryable errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_error_is_reraised_immediately() -> None:
    """AuthenticationError is re-raised — no fallback, no record_failure."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker()

    mock_invoker.invoke.side_effect = lx.AuthenticationError(
        "bad key", llm_provider="openai", model="gpt-4o-mini"
    )

    with pytest.raises(lx.AuthenticationError):
        await fi.invoke(CHAIN_2, MESSAGES, TOKEN_BUDGET)

    mock_invoker.invoke.assert_called_once()
    mock_cb.record_failure.assert_not_called()


@pytest.mark.asyncio
async def test_bad_request_error_is_reraised_immediately() -> None:
    """BadRequestError is re-raised without fallback."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker()

    mock_invoker.invoke.side_effect = lx.BadRequestError(
        "invalid param", llm_provider="openai", model="gpt-4o-mini"
    )

    with pytest.raises(lx.BadRequestError):
        await fi.invoke(CHAIN_2, MESSAGES, TOKEN_BUDGET)

    mock_invoker.invoke.assert_called_once()
    mock_cb.record_failure.assert_not_called()


@pytest.mark.asyncio
async def test_context_window_error_is_reraised_immediately() -> None:
    """ContextWindowExceededError is re-raised without fallback."""
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker()

    mock_invoker.invoke.side_effect = lx.ContextWindowExceededError(
        "too many tokens", llm_provider="openai", model="gpt-4o-mini"
    )

    with pytest.raises(lx.ContextWindowExceededError):
        await fi.invoke(CHAIN_2, MESSAGES, TOKEN_BUDGET)

    mock_invoker.invoke.assert_called_once()
    mock_cb.record_failure.assert_not_called()


# ---------------------------------------------------------------------------
# FallbackEvent logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_event_logged_on_retryable_error(caplog: pytest.LogCaptureFixture) -> None:
    """FallbackEvent is emitted as a warning log entry per fallback attempt."""
    import logging

    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker()

    mock_invoker.invoke.side_effect = [
        lx.RateLimitError("rate limited", llm_provider="openai", model="gpt-4o-mini"),
        _make_response("anthropic/claude-3-haiku"),
    ]

    with caplog.at_level(logging.WARNING, logger="src.model_invoker.fallback_invoker"):
        await fi.invoke(CHAIN_2, MESSAGES, TOKEN_BUDGET)

    assert any("fallback_attempt" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_fallback_event_contains_required_fields() -> None:
    """FallbackEvent log record extra contains primary_model_id, error_code, fallback_model_id."""
    import logging

    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker()

    mock_invoker.invoke.side_effect = [
        lx.RateLimitError("rate limited", llm_provider="openai", model="gpt-4o-mini"),
        _make_response("anthropic/claude-3-haiku"),
    ]

    captured_extras: list[dict] = []

    class _CapturingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.getMessage() == "fallback_attempt":
                captured_extras.append(record.__dict__)

    handler = _CapturingHandler()
    logger = logging.getLogger("src.model_invoker.fallback_invoker")
    logger.addHandler(handler)
    try:
        await fi.invoke(CHAIN_2, MESSAGES, TOKEN_BUDGET)
    finally:
        logger.removeHandler(handler)

    assert len(captured_extras) == 1
    extra = captured_extras[0]
    assert extra["primary_model_id"] == "openai/gpt-4o-mini"
    assert extra["error_code"] == RetryableErrorCode.RATE_LIMITED
    assert extra["fallback_model_id"] == "anthropic/claude-3-haiku"


# ---------------------------------------------------------------------------
# CI benchmark: fallback overhead < 10 ms per attempt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_overhead_under_10ms_per_attempt() -> None:
    """Fallback decision overhead (circuit check + record) is < 10 ms per attempt.

    LiteLLMInvoker is replaced with AsyncMock (0 ms latency) to isolate the
    fallback machinery cost (US-020 AC-6 CI benchmark).
    """
    mock_invoker, mock_cb, fi = _make_invoker_with_circuit_breaker(max_fallback_attempts=3)

    # All calls fail with retryable error
    mock_invoker.invoke.side_effect = lx.RateLimitError(
        "rate limited", llm_provider="openai", model="any"
    )

    start = time.perf_counter()
    result = await fi.invoke(CHAIN_4, MESSAGES, TOKEN_BUDGET)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert isinstance(result, InvocationFailure)
    # 4 attempts × 10 ms budget = 40 ms generous ceiling for CI environments
    assert elapsed_ms < 40, f"Fallback overhead too high: {elapsed_ms:.2f} ms for 4 attempts"
