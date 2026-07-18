"""Tests for ProviderCircuitBreaker (TASK-US020-03).

All Redis interactions use fakeredis.aioredis — no live Redis required.
"""

from __future__ import annotations

import time

import fakeredis.aioredis as fakeredis
import pytest
import pytest_asyncio

from src.model_invoker.circuit_breaker import CircuitState, ProviderCircuitBreaker
from src.model_invoker.config import InvokerSettings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROVIDER = "openai"


def _settings(threshold: int = 5, window_s: int = 60, open_ttl_s: int = 60) -> InvokerSettings:
    return InvokerSettings(
        circuit_failure_threshold=threshold,
        circuit_window_s=window_s,
        circuit_open_ttl_s=open_ttl_s,
    )


@pytest_asyncio.fixture
async def redis() -> fakeredis.FakeRedis:
    r = fakeredis.FakeRedis()
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def cb(redis: fakeredis.FakeRedis) -> ProviderCircuitBreaker:
    return ProviderCircuitBreaker(redis, _settings())


# ---------------------------------------------------------------------------
# is_available — state-key variations
# ---------------------------------------------------------------------------


class TestIsAvailable:
    async def test_returns_true_when_no_state_key(self, cb: ProviderCircuitBreaker) -> None:
        """CLOSED state (absent key) must be treated as available."""
        assert await cb.is_available(PROVIDER) is True

    async def test_returns_false_when_state_is_open(
        self, redis: fakeredis.FakeRedis, cb: ProviderCircuitBreaker
    ) -> None:
        await redis.set(cb._state_key(PROVIDER), "open")
        assert await cb.is_available(PROVIDER) is False

    async def test_returns_true_when_state_is_half_open(
        self, redis: fakeredis.FakeRedis, cb: ProviderCircuitBreaker
    ) -> None:
        await redis.set(cb._state_key(PROVIDER), "half_open")
        assert await cb.is_available(PROVIDER) is True


# ---------------------------------------------------------------------------
# record_failure — sliding window and threshold
# ---------------------------------------------------------------------------


class TestRecordFailure:
    async def test_below_threshold_returns_closed(self, cb: ProviderCircuitBreaker) -> None:
        for _ in range(4):
            state = await cb.record_failure(PROVIDER)
        assert state == CircuitState.CLOSED

    async def test_at_threshold_returns_open(self, cb: ProviderCircuitBreaker) -> None:
        for _ in range(5):
            state = await cb.record_failure(PROVIDER)
        assert state == CircuitState.OPEN

    async def test_open_state_makes_provider_unavailable(
        self, cb: ProviderCircuitBreaker
    ) -> None:
        for _ in range(5):
            await cb.record_failure(PROVIDER)
        assert await cb.is_available(PROVIDER) is False

    async def test_stale_failures_not_counted(self, redis: fakeredis.FakeRedis) -> None:
        """Failures older than circuit_window_s should not count toward threshold."""
        settings = _settings(threshold=3, window_s=60)
        breaker = ProviderCircuitBreaker(redis, settings)

        # Inject 2 stale failures (130 seconds ago — outside the 60 s window)
        stale_ms = int((time.time() - 130) * 1000)
        failures_key = breaker._failures_key(PROVIDER)
        await redis.zadd(failures_key, {f"{stale_ms}:aaa": stale_ms})
        await redis.zadd(failures_key, {f"{stale_ms + 1}:bbb": stale_ms + 1})

        # One fresh failure — total within window = 1, below threshold of 3
        state = await breaker.record_failure(PROVIDER)
        assert state == CircuitState.CLOSED

    async def test_exactly_threshold_with_mixed_window(
        self, redis: fakeredis.FakeRedis
    ) -> None:
        """Stale failures evicted so only in-window ones count."""
        settings = _settings(threshold=3, window_s=60)
        breaker = ProviderCircuitBreaker(redis, settings)

        # Pre-populate 2 stale failures
        stale_ms = int((time.time() - 200) * 1000)
        failures_key = breaker._failures_key(PROVIDER)
        await redis.zadd(failures_key, {f"{stale_ms}:aaa": stale_ms})
        await redis.zadd(failures_key, {f"{stale_ms + 1}:bbb": stale_ms + 1})

        # 3 fresh failures should trip the circuit
        for _ in range(3):
            state = await breaker.record_failure(PROVIDER)
        assert state == CircuitState.OPEN

    async def test_pipeline_used_for_record_failure(
        self, redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """record_failure must use a pipeline (≤ 2 round-trips)."""
        call_count = 0
        original_pipeline = redis.pipeline

        def counting_pipeline(*args: object, **kwargs: object) -> object:
            nonlocal call_count
            call_count += 1
            return original_pipeline(*args, **kwargs)

        monkeypatch.setattr(redis, "pipeline", counting_pipeline)
        settings = _settings(threshold=10)  # won't trip, so no extra SET
        breaker = ProviderCircuitBreaker(redis, settings)
        await breaker.record_failure(PROVIDER)
        # One pipeline() call for the sliding-window operations
        assert call_count == 1


# ---------------------------------------------------------------------------
# record_success — reset behaviour
# ---------------------------------------------------------------------------


class TestRecordSuccess:
    async def test_clears_state_key(
        self, redis: fakeredis.FakeRedis, cb: ProviderCircuitBreaker
    ) -> None:
        await redis.set(cb._state_key(PROVIDER), "open")
        await cb.record_success(PROVIDER)
        assert await redis.get(cb._state_key(PROVIDER)) is None

    async def test_clears_failures_key(
        self, redis: fakeredis.FakeRedis, cb: ProviderCircuitBreaker
    ) -> None:
        for _ in range(3):
            await cb.record_failure(PROVIDER)
        await cb.record_success(PROVIDER)
        assert await redis.zcard(cb._failures_key(PROVIDER)) == 0

    async def test_provider_available_after_success_reset(
        self, cb: ProviderCircuitBreaker
    ) -> None:
        for _ in range(5):
            await cb.record_failure(PROVIDER)
        assert await cb.is_available(PROVIDER) is False
        await cb.record_success(PROVIDER)
        assert await cb.is_available(PROVIDER) is True


# ---------------------------------------------------------------------------
# TTL / HALF_OPEN transition (simulated via fakeredis time travel)
# ---------------------------------------------------------------------------


class TestTtlTransition:
    async def test_available_after_open_ttl_expires(
        self, redis: fakeredis.FakeRedis, cb: ProviderCircuitBreaker
    ) -> None:
        """After circuit_open_ttl_s the state key expires the provider becomes available."""
        for _ in range(5):
            await cb.record_failure(PROVIDER)
        assert await cb.is_available(PROVIDER) is False

        # Simulate TTL expiry: Redis deletes the key when the TTL elapses.
        # Replicate by manually deleting the state key.
        await redis.delete(cb._state_key(PROVIDER))

        assert await cb.is_available(PROVIDER) is True
