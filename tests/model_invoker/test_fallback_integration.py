"""Integration tests for US-020 — Dynamic Model Routing fallback behaviour (TASK-US020-05).

Covers all 6 acceptance criteria using FallbackInvoker, ProviderCircuitBreaker
and mocked LiteLLM responses.  No live Redis or LLM calls are made.
"""

from __future__ import annotations

import logging
import time
from unittest.mock import AsyncMock

import fakeredis.aioredis as fakeredis
import litellm.exceptions as lx
import pytest
import pytest_asyncio

from src.model_invoker.circuit_breaker import CircuitState, ProviderCircuitBreaker
from src.model_invoker.config import InvokerSettings
from src.model_invoker.fallback_invoker import FallbackInvoker
from src.model_invoker.invoker import LiteLLMInvoker
from src.model_invoker.schemas.fallback_chain import FallbackChain, InvocationFailure
from src.model_invoker.schemas.llm_response import LLMResponse

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

CHAIN = FallbackChain(
    model_ids=[
        "gpt-4o-mini",
        "anthropic/claude-3-haiku",
        "mistral/mistral-7b",
        "openai/gpt-3.5-turbo",
    ],
    intent_type="code_generation",
)
MESSAGES = [{"role": "user", "content": "Write a hello-world function."}]
TOKEN_BUDGET = 512


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def redis() -> fakeredis.FakeRedis:
    r = fakeredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def settings() -> InvokerSettings:
    return InvokerSettings(
        max_fallback_attempts=3,
        circuit_failure_threshold=5,
        circuit_window_s=60,
    )


def _make_fi(
    redis: fakeredis.FakeRedis,
    settings: InvokerSettings,
    invoke_mock: AsyncMock,
) -> FallbackInvoker:
    invoker = LiteLLMInvoker()
    invoker.invoke = invoke_mock  # type: ignore[method-assign]
    cb = ProviderCircuitBreaker(redis, settings)
    return FallbackInvoker(invoker, cb, settings)


def _success(model_id: str = "anthropic/claude-3-haiku") -> LLMResponse:
    return LLMResponse(
        model_id=model_id,
        content="ok",
        input_tokens=5,
        output_tokens=2,
        finish_reason="stop",
    )


# ---------------------------------------------------------------------------
# AC-1 — Ordered fallback list: primary tried first, second on primary failure
# ---------------------------------------------------------------------------


async def test_fallback_chain_order(
    redis: fakeredis.FakeRedis, settings: InvokerSettings
) -> None:
    """Primary [0] is tried first; second [1] used on primary failure."""
    invoke_mock = AsyncMock(
        side_effect=[
            lx.RateLimitError("429", llm_provider="openai", model="gpt-4o-mini"),
            _success("anthropic/claude-3-haiku"),
        ]
    )
    fi = _make_fi(redis, settings, invoke_mock)

    result = await fi.invoke(CHAIN, MESSAGES, TOKEN_BUDGET)

    assert isinstance(result, LLMResponse)
    assert result.model_id == "anthropic/claude-3-haiku"
    assert invoke_mock.call_count == 2
    first_call_model = invoke_mock.call_args_list[0].kwargs.get(
        "model_id"
    ) or invoke_mock.call_args_list[0].args[0]
    assert first_call_model == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# AC-2 — HTTP 5xx / 429 / timeout each trigger a fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        lx.APIError(503, "service unavailable", "openai", "gpt-4o-mini"),
        lx.RateLimitError("429", llm_provider="openai", model="gpt-4o-mini"),
        lx.Timeout("timeout", "gpt-4o-mini", "openai"),
    ],
    ids=["http_503", "rate_limit_429", "timeout"],
)
async def test_retryable_errors_trigger_fallback(
    exc: Exception,
    redis: fakeredis.FakeRedis,
    settings: InvokerSettings,
) -> None:
    """Each retryable error class causes exactly one fallback to the next model."""
    success = _success("anthropic/claude-3-haiku")
    invoke_mock = AsyncMock(side_effect=[exc, success])
    fi = _make_fi(redis, settings, invoke_mock)

    result = await fi.invoke(CHAIN, MESSAGES, TOKEN_BUDGET)

    assert isinstance(result, LLMResponse)
    assert result.model_id == "anthropic/claude-3-haiku"
    assert invoke_mock.call_count == 2


# ---------------------------------------------------------------------------
# AC-3 — Maximum 3 fallback attempts (primary + 3 = 4 total tries)
# ---------------------------------------------------------------------------


async def test_max_fallback_attempts_exhausted(
    redis: fakeredis.FakeRedis, settings: InvokerSettings
) -> None:
    """All 4 models fail → InvocationFailure with attempts==4 and all model IDs recorded."""
    invoke_mock = AsyncMock(
        side_effect=[
            lx.RateLimitError("429", llm_provider="openai", model="gpt-4o-mini"),
            lx.RateLimitError("429", llm_provider="anthropic", model="claude-3-haiku"),
            lx.RateLimitError("429", llm_provider="mistral", model="mistral-7b"),
            lx.RateLimitError("429", llm_provider="openai", model="gpt-3.5-turbo"),
        ]
    )
    fi = _make_fi(redis, settings, invoke_mock)

    result = await fi.invoke(CHAIN, MESSAGES, TOKEN_BUDGET)

    assert isinstance(result, InvocationFailure)
    assert result.attempts == 4
    assert len(result.tried_model_ids) == 4
    assert result.tried_model_ids == list(CHAIN.model_ids)


# ---------------------------------------------------------------------------
# AC-4 — Fallback event logged with primary model ID, error code, fallback model ID
# ---------------------------------------------------------------------------


async def test_fallback_event_logged(
    redis: fakeredis.FakeRedis,
    settings: InvokerSettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warning log record emitted on fallback with required identifiers."""
    invoke_mock = AsyncMock(
        side_effect=[
            lx.RateLimitError("429", llm_provider="openai", model="gpt-4o-mini"),
            _success("anthropic/claude-3-haiku"),
        ]
    )
    fi = _make_fi(redis, settings, invoke_mock)

    with caplog.at_level(logging.WARNING, logger="src.model_invoker.fallback_invoker"):
        await fi.invoke(CHAIN, MESSAGES, TOKEN_BUDGET)

    # The FallbackEvent fields are passed as `extra=` kwargs so they appear as
    # attributes on the LogRecord, not in the formatted message text.
    fallback_records = [r for r in caplog.records if r.getMessage() == "fallback_attempt"]
    assert fallback_records, "Expected at least one 'fallback_attempt' log record"
    record = fallback_records[0]
    assert getattr(record, "primary_model_id", None) == "gpt-4o-mini"
    assert getattr(record, "error_code", None) == "rate_limited"
    assert getattr(record, "fallback_model_id", None) == "anthropic/claude-3-haiku"


# ---------------------------------------------------------------------------
# AC-5 — Circuit breaker opens after threshold consecutive failures within window
# ---------------------------------------------------------------------------


async def test_circuit_breaker_opens_after_threshold(
    redis: fakeredis.FakeRedis, settings: InvokerSettings
) -> None:
    """After circuit_failure_threshold failures the circuit opens and blocks the provider."""
    cb = ProviderCircuitBreaker(redis, settings)

    final_state = CircuitState.CLOSED
    for _ in range(settings.circuit_failure_threshold):
        final_state = await cb.record_failure("openai")

    assert final_state == CircuitState.OPEN
    assert not await cb.is_available("openai")


# ---------------------------------------------------------------------------
# AC-6 — Fallback adds ≤ 500 ms overhead per retry (mocked invoker, 0-delay)
# ---------------------------------------------------------------------------


async def test_fallback_overhead_under_500ms(
    redis: fakeredis.FakeRedis, settings: InvokerSettings
) -> None:
    """FallbackInvoker path overhead is well under 500 ms when invoker is a zero-delay mock."""
    invoke_mock = AsyncMock(
        side_effect=[
            lx.RateLimitError("429", llm_provider="openai", model="gpt-4o-mini"),
            _success("anthropic/claude-3-haiku"),
        ]
    )
    fi = _make_fi(redis, settings, invoke_mock)
    chain = FallbackChain(
        model_ids=["gpt-4o-mini", "anthropic/claude-3-haiku"],
        intent_type="general",
    )

    t0 = time.perf_counter()
    await fi.invoke(chain, MESSAGES, TOKEN_BUDGET)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 500, (
        f"Fallback overhead {elapsed_ms:.1f} ms exceeded 500 ms budget"
    )
