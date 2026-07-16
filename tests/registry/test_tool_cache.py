"""
Unit tests for ToolListCache.

TASK-US002-03 acceptance criteria covered:
  - Cache hit: returns deserialized ToolDefinition list
  - Cache miss: returns None
  - Cache set: writes JSON payload with correct TTL
  - Cache invalidate: deletes the key
  - Redis unavailable on get: returns None (no exception)
  - Redis unavailable on set: silently passes (no exception)
  - Redis unavailable on invalidate: silently passes (no exception)
  - ToolRegistryService read-through: miss → DB query → cache set → hit
  - ToolRegistryService: Redis down → falls back to DB, no 500
  - ToolRegistryService: both Redis and DB down → returns empty list
  - Cache invalidation subscriber: message triggers invalidate()
  - Cache invalidation subscriber: non-message events are ignored
  - Cache invalidation subscriber: CancelledError propagates cleanly
  - Cache invalidation subscriber: transient errors trigger reconnect
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from src.gateway.lifespan import _subscribe_invalidation
from src.gateway.schemas.tool_types import InputSchema, ToolDefinition
from src.gateway.services.tool_registry import ToolRegistryService
from src.registry.cache.tool_cache import ToolListCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tools(count: int = 2) -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=f"tool_{i}",
            description=f"Description for tool {i}",
            inputSchema=InputSchema(
                type="object",
                properties={"query": {"type": "string"}},
                required=["query"],
            ),
        )
        for i in range(count)
    ]


async def _make_cache() -> tuple[ToolListCache, fakeredis.aioredis.FakeRedis]:
    """Return (cache, fake_redis) using an in-process fakeredis server."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return ToolListCache(fake), fake


# ---------------------------------------------------------------------------
# ToolListCache.get
# ---------------------------------------------------------------------------


class TestToolListCacheGet:
    @pytest.mark.asyncio
    async def test_returns_none_on_cache_miss(self) -> None:
        cache, _ = await _make_cache()
        assert await cache.get() is None

    @pytest.mark.asyncio
    async def test_returns_tools_on_cache_hit(self) -> None:
        cache, _ = await _make_cache()
        tools = _make_tools(3)
        await cache.set(tools)

        result = await cache.get()

        assert result is not None
        assert len(result) == 3
        assert result[0].name == "tool_0"
        assert result[2].name == "tool_2"

    @pytest.mark.asyncio
    async def test_returns_none_when_redis_unavailable(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = ToolListCache(redis)

        result = await cache.get()

        assert result is None


# ---------------------------------------------------------------------------
# ToolListCache.set
# ---------------------------------------------------------------------------


class TestToolListCacheSet:
    @pytest.mark.asyncio
    async def test_set_writes_with_ttl(self) -> None:
        cache, fake = await _make_cache()
        tools = _make_tools(2)
        await cache.set(tools)

        ttl = await fake.ttl(ToolListCache.KEY)
        assert 0 < ttl <= ToolListCache.TTL_SECONDS

    @pytest.mark.asyncio
    async def test_set_does_not_raise_when_redis_unavailable(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = ToolListCache(redis)

        # Must not raise
        await cache.set(_make_tools(1))

    @pytest.mark.asyncio
    async def test_set_and_get_roundtrip(self) -> None:
        cache, _ = await _make_cache()
        tools = _make_tools(1)
        tools[0] = ToolDefinition(
            name="context_search",
            description="Search for relevant context",
            inputSchema=InputSchema(
                type="object",
                properties={"query": {"type": "string"}},
                required=["query"],
            ),
        )
        await cache.set(tools)
        result = await cache.get()

        assert result is not None
        assert result[0].name == "context_search"
        assert result[0].inputSchema.required == ["query"]


# ---------------------------------------------------------------------------
# ToolListCache.invalidate
# ---------------------------------------------------------------------------


class TestToolListCacheInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_removes_key(self) -> None:
        cache, fake = await _make_cache()
        await cache.set(_make_tools(2))
        assert await cache.get() is not None

        await cache.invalidate()

        assert await cache.get() is None

    @pytest.mark.asyncio
    async def test_invalidate_does_not_raise_when_redis_unavailable(self) -> None:
        redis = AsyncMock()
        redis.delete = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = ToolListCache(redis)

        # Must not raise
        await cache.invalidate()

    @pytest.mark.asyncio
    async def test_invalidate_is_idempotent_on_missing_key(self) -> None:
        cache, _ = await _make_cache()
        # Key does not exist — should not raise
        await cache.invalidate()
        await cache.invalidate()


# ---------------------------------------------------------------------------
# ToolRegistryService read-through pattern
# ---------------------------------------------------------------------------


class TestToolRegistryServiceReadThrough:
    @pytest.mark.asyncio
    async def test_cache_miss_queries_db_and_warms_cache(self) -> None:
        cache, _ = await _make_cache()

        db_tool = MagicMock()
        db_tool.name = "get_context"
        db_tool.description = "Get context"
        db_tool.input_schema = {"properties": {}, "required": []}

        repo = AsyncMock()
        repo.find_active = AsyncMock(return_value=[db_tool])

        svc = ToolRegistryService(cache=cache, repo=repo)

        # First call: cache miss → DB
        result1 = await svc.get_active_tools()
        assert len(result1.tools) == 1
        assert result1.tools[0].name == "get_context"
        repo.find_active.assert_awaited_once()

        # Second call: cache hit — DB must not be called again
        result2 = await svc.get_active_tools()
        assert len(result2.tools) == 1
        repo.find_active.assert_awaited_once()  # still only once

    @pytest.mark.asyncio
    async def test_cache_hit_returns_without_db_query(self) -> None:
        cache, _ = await _make_cache()
        await cache.set(_make_tools(2))

        repo = AsyncMock()
        svc = ToolRegistryService(cache=cache, repo=repo)

        result = await svc.get_active_tools()

        assert len(result.tools) == 2
        repo.find_active.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_redis_down_falls_back_to_db(self) -> None:
        broken_redis = AsyncMock()
        broken_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        broken_redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = ToolListCache(broken_redis)

        db_tool = MagicMock()
        db_tool.name = "fallback_tool"
        db_tool.description = "Fallback"
        db_tool.input_schema = {"properties": {}, "required": []}

        repo = AsyncMock()
        repo.find_active = AsyncMock(return_value=[db_tool])

        svc = ToolRegistryService(cache=cache, repo=repo)

        result = await svc.get_active_tools()

        assert len(result.tools) == 1
        assert result.tools[0].name == "fallback_tool"

    @pytest.mark.asyncio
    async def test_both_redis_and_db_down_returns_empty_list(self) -> None:
        broken_redis = AsyncMock()
        broken_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = ToolListCache(broken_redis)

        repo = AsyncMock()
        repo.find_active = AsyncMock(side_effect=Exception("DB connection failed"))

        svc = ToolRegistryService(cache=cache, repo=repo)

        result = await svc.get_active_tools()

        assert result.tools == []

    @pytest.mark.asyncio
    async def test_no_cache_no_repo_returns_empty_list(self) -> None:
        svc = ToolRegistryService(cache=None, repo=None)
        result = await svc.get_active_tools()
        assert result.tools == []


# ---------------------------------------------------------------------------
# Cache invalidation subscriber
# ---------------------------------------------------------------------------


class TestCacheInvalidationSubscriber:
    @pytest.mark.asyncio
    async def test_message_triggers_invalidate(self) -> None:
        """A 'message' type pub/sub event calls cache.invalidate() once."""
        cache = AsyncMock(spec=ToolListCache)

        async def _fake_listen():
            yield {"type": "subscribe", "data": 1}
            yield {"type": "message", "data": '{"tool": "t1", "action": "created"}'}
            raise asyncio.CancelledError()  # clean exit — CancelledError is BaseException

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = _fake_listen

        redis = MagicMock()
        redis.pubsub = MagicMock(return_value=pubsub)

        with pytest.raises(asyncio.CancelledError):
            await _subscribe_invalidation(redis, cache)

        cache.invalidate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_message_events_are_ignored(self) -> None:
        """subscribe/psubscribe control events must not call invalidate()."""
        cache = AsyncMock(spec=ToolListCache)

        async def _fake_listen():
            yield {"type": "subscribe", "data": 1}
            yield {"type": "psubscribe", "data": 1}
            raise asyncio.CancelledError()

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = _fake_listen

        redis = MagicMock()
        redis.pubsub = MagicMock(return_value=pubsub)

        with pytest.raises(asyncio.CancelledError):
            await _subscribe_invalidation(redis, cache)

        cache.invalidate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self) -> None:
        """CancelledError is never swallowed — the subscriber shuts down cleanly."""
        cache = AsyncMock(spec=ToolListCache)

        async def _fake_listen():
            yield {"type": "subscribe", "data": 1}
            raise asyncio.CancelledError()

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = _fake_listen

        redis = MagicMock()
        redis.pubsub = MagicMock(return_value=pubsub)

        with pytest.raises(asyncio.CancelledError):
            await _subscribe_invalidation(redis, cache)

    @pytest.mark.asyncio
    async def test_transient_error_reconnects(self) -> None:
        """A transient Redis error triggers asyncio.sleep(2) then reconnects."""
        cache = AsyncMock(spec=ToolListCache)
        call_count = 0

        async def _fail_once_then_exit():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Redis blip")
            # Second invocation: terminate with CancelledError
            raise asyncio.CancelledError()
            yield  # noqa: unreachable — makes this an async generator at compile time

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = _fail_once_then_exit

        redis = MagicMock()
        redis.pubsub = MagicMock(return_value=pubsub)

        with patch("src.gateway.lifespan.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(asyncio.CancelledError):
                await _subscribe_invalidation(redis, cache)

        assert call_count == 2
        mock_sleep.assert_awaited_once_with(2)

    @pytest.mark.asyncio
    async def test_start_cache_invalidation_subscriber_delegates(self) -> None:
        """start_cache_invalidation_subscriber delegates to _subscribe_invalidation."""
        from src.gateway.lifespan import start_cache_invalidation_subscriber

        cache = AsyncMock(spec=ToolListCache)

        async def _fake_listen():
            yield {"type": "subscribe", "data": 1}
            raise asyncio.CancelledError()

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = _fake_listen

        redis = MagicMock()
        redis.pubsub = MagicMock(return_value=pubsub)

        with pytest.raises(asyncio.CancelledError):
            await start_cache_invalidation_subscriber(redis, cache)
