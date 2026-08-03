"""Unit tests for ScoredModelCache (TASK-US019-02).

Uses fakeredis.aioredis so no live Redis instance is required in CI.
"""

from __future__ import annotations

import fakeredis.aioredis as fakeredis
import pytest
import pytest_asyncio

from src.model_router.cache.scored_model_cache import ScoredModelCache
from src.model_router.schemas.model_score import ModelScore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _score(model_id: str, composite: float = 0.75) -> ModelScore:
    return ModelScore(
        model_id=model_id,
        quality_score=0.8,
        normalised_cost=50.0,
        normalised_latency=0.5,
        composite_score=composite,
    )


@pytest_asyncio.fixture()
async def redis_client() -> fakeredis.FakeRedis:  # type: ignore[return]
    client = fakeredis.FakeRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture()
async def cache(redis_client: fakeredis.FakeRedis) -> ScoredModelCache:
    return ScoredModelCache(redis=redis_client)


# ---------------------------------------------------------------------------
# get — cold cache
# ---------------------------------------------------------------------------


class TestScoredModelCacheGet:
    @pytest.mark.asyncio
    async def test_returns_none_on_cold_cache(self, cache: ScoredModelCache) -> None:
        result = await cache.get("code_generation")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_intent(self, cache: ScoredModelCache) -> None:
        result = await cache.get("non_existent_intent")
        assert result is None


# ---------------------------------------------------------------------------
# set + get round-trip
# ---------------------------------------------------------------------------


class TestScoredModelCacheSetGet:
    @pytest.mark.asyncio
    async def test_round_trip_preserves_model_ids(self, cache: ScoredModelCache) -> None:
        scores = [_score("gpt-4o"), _score("claude-3-haiku")]
        await cache.set("chat", scores)
        result = await cache.get("chat")
        assert result is not None
        assert [s.model_id for s in result] == ["gpt-4o", "claude-3-haiku"]

    @pytest.mark.asyncio
    async def test_round_trip_preserves_all_fields(self, cache: ScoredModelCache) -> None:
        original = _score("gpt-4o-mini", composite=1.23)
        await cache.set("summarization", [original])
        result = await cache.get("summarization")
        assert result is not None
        assert len(result) == 1
        restored = result[0]
        assert restored.model_id == original.model_id
        assert restored.quality_score == original.quality_score
        assert restored.normalised_cost == original.normalised_cost
        assert restored.normalised_latency == original.normalised_latency
        assert restored.composite_score == original.composite_score

    @pytest.mark.asyncio
    async def test_round_trip_empty_list(self, cache: ScoredModelCache) -> None:
        await cache.set("embedding", [])
        result = await cache.get("embedding")
        assert result == []

    @pytest.mark.asyncio
    async def test_different_intents_stored_independently(
        self, cache: ScoredModelCache
    ) -> None:
        await cache.set("chat", [_score("model-a")])
        await cache.set("code_generation", [_score("model-b")])

        chat_result = await cache.get("chat")
        code_result = await cache.get("code_generation")

        assert chat_result is not None and chat_result[0].model_id == "model-a"
        assert code_result is not None and code_result[0].model_id == "model-b"


# ---------------------------------------------------------------------------
# TTL
# ---------------------------------------------------------------------------


class TestScoredModelCacheTTL:
    @pytest.mark.asyncio
    async def test_ttl_is_thirty_seconds(
        self, cache: ScoredModelCache, redis_client: fakeredis.FakeRedis
    ) -> None:
        await cache.set("latency_sensitive", [_score("fast-model")])
        key = cache._key("latency_sensitive")
        pttl = await redis_client.pttl(key)
        # PTTL returns milliseconds; allow ±200 ms tolerance for test execution
        assert 29_800 <= pttl <= 30_000, f"PTTL was {pttl} ms, expected ~30 000 ms"


# ---------------------------------------------------------------------------
# invalidate
# ---------------------------------------------------------------------------


class TestScoredModelCacheInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_removes_single_key(self, cache: ScoredModelCache) -> None:
        await cache.set("chat", [_score("model-a")])
        await cache.invalidate("chat")
        assert await cache.get("chat") is None

    @pytest.mark.asyncio
    async def test_invalidate_leaves_other_keys_intact(
        self, cache: ScoredModelCache
    ) -> None:
        await cache.set("chat", [_score("model-a")])
        await cache.set("code_generation", [_score("model-b")])
        await cache.invalidate("chat")
        assert await cache.get("chat") is None
        assert await cache.get("code_generation") is not None


# ---------------------------------------------------------------------------
# invalidate_all — uses SCAN, not KEYS
# ---------------------------------------------------------------------------


class TestScoredModelCacheInvalidateAll:
    @pytest.mark.asyncio
    async def test_invalidate_all_clears_every_scored_key(
        self, cache: ScoredModelCache
    ) -> None:
        intents = ["chat", "code_generation", "summarization", "embedding"]
        for intent in intents:
            await cache.set(intent, [_score(f"model-{intent}")])

        await cache.invalidate_all()

        for intent in intents:
            assert await cache.get(intent) is None

    @pytest.mark.asyncio
    async def test_invalidate_all_uses_scan_not_keys(
        self, cache: ScoredModelCache, redis_client: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify invalidate_all() calls redis.scan() and never calls redis.keys()."""
        scan_calls: list = []
        keys_calls: list = []

        original_scan = redis_client.scan

        async def recording_scan(*args: object, **kwargs: object) -> object:
            scan_calls.append((args, kwargs))
            return await original_scan(*args, **kwargs)

        async def forbidden_keys(*args: object, **kwargs: object) -> object:  # pragma: no cover
            keys_calls.append((args, kwargs))
            raise AssertionError("invalidate_all() must not call redis.keys()")

        monkeypatch.setattr(redis_client, "scan", recording_scan)
        monkeypatch.setattr(redis_client, "keys", forbidden_keys)

        await cache.set("chat", [_score("model-a")])
        await cache.invalidate_all()

        assert len(scan_calls) >= 1, "scan() was never called"
        assert len(keys_calls) == 0, "keys() must not be called"

    @pytest.mark.asyncio
    async def test_invalidate_all_idempotent_on_empty_cache(
        self, cache: ScoredModelCache
    ) -> None:
        # Should complete without error when no keys exist
        await cache.invalidate_all()
