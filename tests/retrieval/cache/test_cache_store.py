"""Unit tests for TASK-US013-02 — ContextCacheStore: Redis read/write with per-source TTL.

All tests use fakeredis.aioredis; no live Redis connection is required.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import fakeredis.aioredis
import pytest
import pytest_asyncio

from src.retrieval.cache.cache_key import ContextCacheKey, make_cache_key
from src.retrieval.cache.cache_store import (
    DEFAULT_TTL,
    TTL_CONFIG,
    ContextCacheStore,
    assert_ttl_coverage,
)
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_chunk(
    n: int,
    source_id: str = "github",
    score: float = 0.9,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"abc{n:013d}",
        source_id=source_id,
        content=f"chunk content {n}",
        score=score,
        metadata=ChunkMetadata(
            file_path=f"src/file_{n}.py",
            timestamp=_NOW,
            author="alice",
            url=f"https://github.com/org/repo/blob/main/src/file_{n}.py",
            chunk_index=n,
        ),
        search_mode="rrf",
    )


def _make_chunks(count: int, source_id: str = "github") -> list[RetrievedChunk]:
    return [_make_chunk(i, source_id=source_id) for i in range(count)]


@pytest_asyncio.fixture
async def redis_client() -> fakeredis.aioredis.FakeRedis:
    client: fakeredis.aioredis.FakeRedis = await fakeredis.aioredis.FakeRedis(
        decode_responses=False
    )
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def store(redis_client: fakeredis.aioredis.FakeRedis) -> ContextCacheStore:
    return ContextCacheStore(redis=redis_client)


def _key(source_id: str = "github", budget: int = 2000) -> ContextCacheKey:
    return make_cache_key(source_id, [0.1, 0.2, 0.3, 0.4, 0.5], budget)


# ---------------------------------------------------------------------------
# get — cache miss
# ---------------------------------------------------------------------------


class TestGet:
    @pytest.mark.asyncio
    async def test_miss_returns_none(self, store: ContextCacheStore) -> None:
        key = _key("github")
        result = await store.get(key)
        assert result is None

    @pytest.mark.asyncio
    async def test_miss_for_unknown_source(self, store: ContextCacheStore) -> None:
        key = _key("unknown_source_xyz")
        result = await store.get(key)
        assert result is None


# ---------------------------------------------------------------------------
# set / get — round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.asyncio
    async def test_set_then_get_returns_original_chunks(
        self, store: ContextCacheStore
    ) -> None:
        key = _key("github")
        chunks = _make_chunks(3, source_id="github")
        await store.set(key, chunks)
        result = await store.get(key)
        assert result == chunks

    @pytest.mark.asyncio
    async def test_round_trip_preserves_all_fields(
        self, store: ContextCacheStore
    ) -> None:
        key = _key("confluence")
        chunks = _make_chunks(1, source_id="confluence")
        await store.set(key, chunks)
        result = await store.get(key)
        assert result is not None
        assert len(result) == 1
        chunk = result[0]
        assert chunk.chunk_id == chunks[0].chunk_id
        assert chunk.source_id == "confluence"
        assert chunk.content == chunks[0].content
        assert chunk.score == chunks[0].score
        assert chunk.search_mode == "rrf"
        assert chunk.metadata.file_path == chunks[0].metadata.file_path
        assert chunk.metadata.timestamp == _NOW
        assert chunk.metadata.author == "alice"

    @pytest.mark.asyncio
    async def test_round_trip_empty_list(self, store: ContextCacheStore) -> None:
        key = _key("jira")
        await store.set(key, [])
        result = await store.get(key)
        assert result == []

    @pytest.mark.asyncio
    async def test_distinct_keys_independent(
        self, store: ContextCacheStore
    ) -> None:
        key_a = _key("github", budget=1000)
        key_b = _key("github", budget=2000)
        chunks_a = _make_chunks(1, source_id="github")
        chunks_b = _make_chunks(2, source_id="github")
        await store.set(key_a, chunks_a)
        await store.set(key_b, chunks_b)
        assert await store.get(key_a) == chunks_a
        assert await store.get(key_b) == chunks_b


# ---------------------------------------------------------------------------
# set — TTL enforcement
# ---------------------------------------------------------------------------


class TestTTL:
    @pytest.mark.asyncio
    async def test_github_ttl_is_300_seconds(
        self,
        redis_client: fakeredis.aioredis.FakeRedis,
        store: ContextCacheStore,
    ) -> None:
        key = _key("github")
        await store.set(key, _make_chunks(1))
        from src.retrieval.cache.cache_key import redis_key

        ttl = await redis_client.ttl(redis_key(key))
        assert ttl == TTL_CONFIG["github"]
        assert ttl == 300

    @pytest.mark.asyncio
    async def test_confluence_ttl_is_1800_seconds(
        self,
        redis_client: fakeredis.aioredis.FakeRedis,
        store: ContextCacheStore,
    ) -> None:
        key = _key("confluence")
        await store.set(key, _make_chunks(1, source_id="confluence"))
        from src.retrieval.cache.cache_key import redis_key

        ttl = await redis_client.ttl(redis_key(key))
        assert ttl == TTL_CONFIG["confluence"]
        assert ttl == 1800

    @pytest.mark.asyncio
    async def test_grafana_ttl_is_120_seconds(
        self,
        redis_client: fakeredis.aioredis.FakeRedis,
        store: ContextCacheStore,
    ) -> None:
        key = _key("grafana")
        await store.set(key, _make_chunks(1, source_id="grafana"))
        from src.retrieval.cache.cache_key import redis_key

        ttl = await redis_client.ttl(redis_key(key))
        assert ttl == TTL_CONFIG["grafana"]
        assert ttl == 120

    @pytest.mark.asyncio
    async def test_unknown_source_uses_default_ttl(
        self,
        redis_client: fakeredis.aioredis.FakeRedis,
        store: ContextCacheStore,
    ) -> None:
        key = _key("unregistered_source_abc")
        await store.set(key, _make_chunks(1))
        from src.retrieval.cache.cache_key import redis_key

        ttl = await redis_client.ttl(redis_key(key))
        assert ttl == DEFAULT_TTL
        assert ttl == 600

    @pytest.mark.asyncio
    async def test_custom_ttl_config_overrides_default(
        self, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        custom_store = ContextCacheStore(
            redis=redis_client, ttl_config={"github": 42}
        )
        key = _key("github")
        await custom_store.set(key, _make_chunks(1))
        from src.retrieval.cache.cache_key import redis_key

        ttl = await redis_client.ttl(redis_key(key))
        assert ttl == 42


# ---------------------------------------------------------------------------
# get — 50 ms deserialization budget
# ---------------------------------------------------------------------------


class TestDeserializationPerformance:
    @pytest.mark.asyncio
    async def test_get_20_chunks_within_50ms(
        self, store: ContextCacheStore
    ) -> None:
        key = _key("github")
        chunks = _make_chunks(20)
        await store.set(key, chunks)

        start = time.perf_counter()
        result = await store.get(key)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None
        assert len(result) == 20
        assert elapsed_ms < 50, f"get() took {elapsed_ms:.1f} ms — exceeds 50 ms budget"


# ---------------------------------------------------------------------------
# invalidate_source
# ---------------------------------------------------------------------------


class TestInvalidateSource:
    @pytest.mark.asyncio
    async def test_invalidate_deletes_all_keys_for_source(
        self, store: ContextCacheStore
    ) -> None:
        keys = [
            make_cache_key("github", [0.1 * i, 0.2, 0.3], 2000) for i in range(1, 6)
        ]
        for k in keys:
            await store.set(k, _make_chunks(2))

        deleted = await store.invalidate_source("github")
        assert deleted == 5
        for k in keys:
            assert await store.get(k) is None

    @pytest.mark.asyncio
    async def test_invalidate_returns_count(
        self, store: ContextCacheStore
    ) -> None:
        keys = [make_cache_key("jira", [float(i), 0.0], 1000) for i in range(3)]
        for k in keys:
            await store.set(k, _make_chunks(1))

        count = await store.invalidate_source("jira")
        assert count == 3

    @pytest.mark.asyncio
    async def test_invalidate_only_affects_target_source(
        self, store: ContextCacheStore
    ) -> None:
        github_key = _key("github", budget=1000)
        confluence_key = _key("confluence", budget=1000)
        chunks = _make_chunks(1)

        await store.set(github_key, chunks)
        await store.set(confluence_key, chunks)

        await store.invalidate_source("github")

        assert await store.get(github_key) is None
        assert await store.get(confluence_key) == chunks

    @pytest.mark.asyncio
    async def test_invalidate_empty_source_returns_zero(
        self, store: ContextCacheStore
    ) -> None:
        count = await store.invalidate_source("nonexistent_source")
        assert count == 0


# ---------------------------------------------------------------------------
# assert_ttl_coverage
# ---------------------------------------------------------------------------


class TestAssertTTLCoverage:
    def test_passes_for_all_known_sources(self) -> None:
        assert_ttl_coverage(set(TTL_CONFIG.keys()))

    def test_passes_for_subset_of_known_sources(self) -> None:
        assert_ttl_coverage({"github", "jira", "confluence"})

    def test_passes_for_empty_set(self) -> None:
        assert_ttl_coverage(set())

    def test_raises_for_missing_source(self) -> None:
        with pytest.raises(AssertionError, match="TTL_CONFIG is missing entries"):
            assert_ttl_coverage({"github", "mystery_connector_xyz"})

    def test_source_map_sources_are_covered(self) -> None:
        from src.agents.source_selector import SOURCE_MAP

        all_sources = {s for sources in SOURCE_MAP.values() for s in sources}
        assert_ttl_coverage(all_sources)
