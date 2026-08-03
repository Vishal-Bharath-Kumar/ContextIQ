"""Unit tests for ModelListCache and the model-registry pub/sub invalidation subscriber.

TASK-US018-05 acceptance criteria covered:
  - Cache miss: returns None on cold cache
  - Cache set + get round-trip: returns original model list
  - Cache invalidate: deletes the key; next get() returns None
  - TTL: set to 60 seconds as safety net (PTTL assertion)
  - Redis unavailable on get: returns None (no exception)
  - Redis unavailable on set: silently passes (no exception)
  - Redis unavailable on invalidate: silently passes (no exception)
  - Pub/sub subscriber: calls invalidate() on 'message' type events
  - Pub/sub subscriber: non-message events are ignored
  - Pub/sub subscriber: CancelledError propagates cleanly
  - Pub/sub subscriber: transient errors trigger reconnect after 2 s
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import fakeredis.aioredis
import pytest

from src.agents.worker.lifespan import _model_cache_invalidator
from src.model_registry.cache.model_cache import ModelListCache
from src.model_registry.schemas.model_definition import (
    LatencyTier,
    ModelCapability,
    ModelDefinition,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_models(count: int = 2) -> list[ModelDefinition]:
    return [
        ModelDefinition(
            id=uuid4(),
            model_id=f"gpt-4o-mini-{i}",
            provider="openai",
            context_window=128_000,
            cost_per_1k_tokens=0.15,
            latency_tier=LatencyTier.FAST,
            capabilities=[ModelCapability.CHAT],
            is_active=True,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        for i in range(count)
    ]


async def _make_cache() -> tuple[ModelListCache, fakeredis.aioredis.FakeRedis]:
    """Return (cache, fake_redis) using an in-process fakeredis server."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return ModelListCache(fake), fake


# ---------------------------------------------------------------------------
# ModelListCache.get
# ---------------------------------------------------------------------------


class TestModelListCacheGet:
    @pytest.mark.asyncio
    async def test_returns_none_on_cold_cache(self) -> None:
        cache, _ = await _make_cache()
        assert await cache.get() is None

    @pytest.mark.asyncio
    async def test_returns_models_on_cache_hit(self) -> None:
        cache, _ = await _make_cache()
        models = _make_models(3)
        await cache.set(models)

        result = await cache.get()

        assert result is not None
        assert len(result) == 3
        assert result[0].model_id == "gpt-4o-mini-0"
        assert result[2].model_id == "gpt-4o-mini-2"

    @pytest.mark.asyncio
    async def test_returns_none_when_redis_unavailable(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = ModelListCache(redis)

        result = await cache.get()

        assert result is None


# ---------------------------------------------------------------------------
# ModelListCache.set
# ---------------------------------------------------------------------------


class TestModelListCacheSet:
    @pytest.mark.asyncio
    async def test_set_writes_with_ttl(self) -> None:
        cache, fake = await _make_cache()
        models = _make_models(2)
        await cache.set(models)

        ttl = await fake.ttl(ModelListCache.KEY)
        assert 0 < ttl <= ModelListCache.TTL_SECONDS

    @pytest.mark.asyncio
    async def test_ttl_is_60_seconds(self) -> None:
        cache, fake = await _make_cache()
        models = _make_models(1)
        await cache.set(models)

        pttl = await fake.pttl(ModelListCache.KEY)
        # pttl returns milliseconds; safety-net TTL must be ≤ 60 000 ms
        assert 0 < pttl <= 60_000

    @pytest.mark.asyncio
    async def test_set_does_not_raise_when_redis_unavailable(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = ModelListCache(redis)

        await cache.set(_make_models(1))  # must not raise

    @pytest.mark.asyncio
    async def test_set_and_get_roundtrip(self) -> None:
        cache, _ = await _make_cache()
        models = _make_models(2)

        await cache.set(models)
        result = await cache.get()

        assert result is not None
        assert len(result) == 2
        assert result[0].model_id == models[0].model_id
        assert result[1].provider == "openai"
        assert result[0].latency_tier == LatencyTier.FAST
        assert ModelCapability.CHAT in result[0].capabilities


# ---------------------------------------------------------------------------
# ModelListCache.invalidate
# ---------------------------------------------------------------------------


class TestModelListCacheInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_removes_key(self) -> None:
        cache, _ = await _make_cache()
        await cache.set(_make_models(2))
        assert await cache.get() is not None

        await cache.invalidate()

        assert await cache.get() is None

    @pytest.mark.asyncio
    async def test_invalidate_does_not_raise_when_redis_unavailable(self) -> None:
        redis = AsyncMock()
        redis.delete = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = ModelListCache(redis)

        await cache.invalidate()  # must not raise

    @pytest.mark.asyncio
    async def test_invalidate_is_idempotent_on_missing_key(self) -> None:
        cache, _ = await _make_cache()
        await cache.invalidate()
        await cache.invalidate()  # second call must not raise


# ---------------------------------------------------------------------------
# Pub/sub invalidation subscriber
# ---------------------------------------------------------------------------


class TestModelCacheInvalidationSubscriber:
    @pytest.mark.asyncio
    async def test_message_triggers_invalidate(self) -> None:
        """A 'message' type pub/sub event calls cache.invalidate() once."""
        cache = AsyncMock(spec=ModelListCache)

        async def _fake_listen() -> None:  # type: ignore[return]
            yield {"type": "subscribe", "data": 1}
            yield {"type": "message", "data": '{"event": "model_registered", "model_id": "gpt-4o"}'}
            raise asyncio.CancelledError()

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = _fake_listen

        redis = MagicMock()
        redis.pubsub = MagicMock(return_value=pubsub)

        with pytest.raises(asyncio.CancelledError):
            await _model_cache_invalidator(redis, cache)

        cache.invalidate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_message_events_are_ignored(self) -> None:
        """subscribe/psubscribe control events must not call invalidate()."""
        cache = AsyncMock(spec=ModelListCache)

        async def _fake_listen() -> None:  # type: ignore[return]
            yield {"type": "subscribe", "data": 1}
            yield {"type": "psubscribe", "data": 1}
            raise asyncio.CancelledError()

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = _fake_listen

        redis = MagicMock()
        redis.pubsub = MagicMock(return_value=pubsub)

        with pytest.raises(asyncio.CancelledError):
            await _model_cache_invalidator(redis, cache)

        cache.invalidate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates_cleanly(self) -> None:
        """CancelledError is never swallowed — the subscriber shuts down cleanly."""
        cache = AsyncMock(spec=ModelListCache)

        async def _fake_listen() -> None:  # type: ignore[return]
            yield {"type": "subscribe", "data": 1}
            raise asyncio.CancelledError()

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = _fake_listen

        redis = MagicMock()
        redis.pubsub = MagicMock(return_value=pubsub)

        with pytest.raises(asyncio.CancelledError):
            await _model_cache_invalidator(redis, cache)

    @pytest.mark.asyncio
    async def test_transient_error_triggers_reconnect(self) -> None:
        """A transient Redis error triggers asyncio.sleep(2) then reconnects."""
        cache = AsyncMock(spec=ModelListCache)
        call_count = 0

        async def _fail_once_then_exit() -> None:  # type: ignore[return]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Redis blip")
            # Second invocation: terminate with CancelledError
            raise asyncio.CancelledError()
            yield  # noqa: RET504 — makes this an async generator at compile time

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = _fail_once_then_exit

        redis = MagicMock()
        redis.pubsub = MagicMock(return_value=pubsub)

        with patch("src.agents.worker.lifespan.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(asyncio.CancelledError):
                await _model_cache_invalidator(redis, cache)

        assert call_count == 2
        mock_sleep.assert_awaited_once_with(2)
