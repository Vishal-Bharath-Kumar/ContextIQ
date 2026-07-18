"""Unit tests for context retrieval cache Prometheus metrics — TASK-US013-04.

Coverage:
  - Hit increments context_cache_requests_total{source_id=..., result="hit"}.
  - Miss increments context_cache_requests_total{source_id=..., result="miss"}.
  - context_cache_hit_ratio equals hits / (hits + misses) after mixed traffic.
  - context_cache_hit_ratio is 0.0 at initial state (no requests processed).
  - Both metrics are present in the /metrics scrape output (generate_latest).

All tests run against a fresh CollectorRegistry; no live Prometheus server
or push-gateway is required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

import src.retrieval.cache.metrics as metrics_mod
import src.retrieval.engine.cached_hybrid_search as engine_mod
from src.retrieval.engine.cached_hybrid_search import CachedHybridSearchEngine
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk, make_chunk_id

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_METADATA = ChunkMetadata(
    file_path="src/main.py",
    timestamp=datetime(2024, 1, 1, tzinfo=UTC),
    author="dev",
    url=None,
    chunk_index=0,
)


def _make_chunk(
    source_id: str = "github",
    content: str = "sample chunk",
    score: float = 0.9,
    idx: int = 0,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=make_chunk_id(source_id, "src/main.py", idx),
        source_id=source_id,
        content=content,
        score=score,
        metadata=_METADATA,
        search_mode="rrf",
    )


def _make_chunks(n: int, source_id: str = "github") -> list[RetrievedChunk]:
    return [
        _make_chunk(source_id=source_id, content=f"chunk {i}", score=0.9 - i * 0.01, idx=i)
        for i in range(n)
    ]


def _sample_value(
    registry: CollectorRegistry, metric_name: str, labels: dict[str, str]
) -> float | None:
    """Return the value of a sample matching *metric_name* prefix and *labels*.

    Counter samples in prometheus_client are suffixed with ``_total``; this
    helper matches on *startswith* so it works regardless of whether the caller
    already includes the suffix.
    """
    for metric_family in registry.collect():
        for sample in metric_family.samples:
            if sample.name.startswith(metric_name) and sample.labels == labels:
                return sample.value
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_metrics(monkeypatch: pytest.MonkeyPatch) -> CollectorRegistry:
    """Provide isolated, fresh Prometheus metrics for every test.

    Patches both the ``metrics`` module and the ``cached_hybrid_search``
    module so that the engine uses counters registered on the fresh registry.
    Also resets the class-level in-process hit/miss totals.
    """
    registry = CollectorRegistry()

    fresh_counter = Counter(
        "context_cache_requests_total",
        "Total cache probe attempts by source and outcome",
        labelnames=["source_id", "result"],
        registry=registry,
    )
    fresh_gauge = Gauge(
        "context_cache_hit_ratio",
        "Rolling cache hit ratio across all sources (updated on every probe)",
        registry=registry,
    )

    monkeypatch.setattr(metrics_mod, "context_cache_requests_total", fresh_counter)
    monkeypatch.setattr(metrics_mod, "context_cache_hit_ratio", fresh_gauge)
    monkeypatch.setattr(engine_mod, "context_cache_requests_total", fresh_counter)
    monkeypatch.setattr(engine_mod, "context_cache_hit_ratio", fresh_gauge)

    # Reset in-process counters so tests are independent
    CachedHybridSearchEngine._hits = 0
    CachedHybridSearchEngine._misses = 0

    yield registry

    # Cleanup after each test
    CachedHybridSearchEngine._hits = 0
    CachedHybridSearchEngine._misses = 0


@pytest.fixture()
def mock_engine() -> AsyncMock:
    engine = AsyncMock()
    engine.search = AsyncMock(return_value=_make_chunks(3))
    return engine


@pytest.fixture()
def mock_cache() -> AsyncMock:
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)  # default: cache miss
    cache.set = AsyncMock(return_value=None)
    return cache


@pytest.fixture()
def mock_embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.embed = MagicMock(return_value=[0.1, 0.2, 0.3])
    return embedder


@pytest_asyncio.fixture()
async def cached_engine(
    mock_engine: AsyncMock,
    mock_cache: AsyncMock,
    mock_embedder: MagicMock,
) -> CachedHybridSearchEngine:
    return CachedHybridSearchEngine(
        engine=mock_engine,
        cache=mock_cache,
        embedder=mock_embedder,
    )


# ---------------------------------------------------------------------------
# Tests — initial state
# ---------------------------------------------------------------------------


def test_hit_ratio_initial_state(_fresh_metrics: CollectorRegistry) -> None:
    """context_cache_hit_ratio is 0.0 when no requests have been processed."""
    value = _sample_value(_fresh_metrics, "context_cache_hit_ratio", {})
    # Gauge defaults to 0.0 at registration time
    assert value == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests — cache hit path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_increments_hit_counter(
    cached_engine: CachedHybridSearchEngine,
    mock_cache: AsyncMock,
    _fresh_metrics: CollectorRegistry,
) -> None:
    """Cache hit increments the 'hit' label of context_cache_requests_total."""
    mock_cache.get = AsyncMock(return_value=_make_chunks(2))

    await cached_engine.search("query", source_id="github", token_budget=500)

    value = _sample_value(
        _fresh_metrics,
        "context_cache_requests_total",
        {"source_id": "github", "result": "hit"},
    )
    assert value == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_cache_hit_does_not_increment_miss_counter(
    cached_engine: CachedHybridSearchEngine,
    mock_cache: AsyncMock,
    _fresh_metrics: CollectorRegistry,
) -> None:
    """A cache hit must not touch the 'miss' counter."""
    mock_cache.get = AsyncMock(return_value=_make_chunks(2))

    await cached_engine.search("query", source_id="github", token_budget=500)

    # Miss counter should be absent or zero
    value = _sample_value(
        _fresh_metrics,
        "context_cache_requests_total",
        {"source_id": "github", "result": "miss"},
    )
    assert value is None or value == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests — cache miss path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_increments_miss_counter(
    cached_engine: CachedHybridSearchEngine,
    _fresh_metrics: CollectorRegistry,
) -> None:
    """Cache miss increments the 'miss' label of context_cache_requests_total."""
    await cached_engine.search("query", source_id="github", token_budget=500)

    value = _sample_value(
        _fresh_metrics,
        "context_cache_requests_total",
        {"source_id": "github", "result": "miss"},
    )
    assert value == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_cache_miss_does_not_increment_hit_counter(
    cached_engine: CachedHybridSearchEngine,
    _fresh_metrics: CollectorRegistry,
) -> None:
    """A cache miss must not touch the 'hit' counter."""
    await cached_engine.search("query", source_id="github", token_budget=500)

    value = _sample_value(
        _fresh_metrics,
        "context_cache_requests_total",
        {"source_id": "github", "result": "hit"},
    )
    assert value is None or value == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests — hit ratio calculation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hit_ratio_all_hits(
    cached_engine: CachedHybridSearchEngine,
    mock_cache: AsyncMock,
    _fresh_metrics: CollectorRegistry,
) -> None:
    """Ratio is 1.0 when all requests are cache hits."""
    mock_cache.get = AsyncMock(return_value=_make_chunks(2))

    for _ in range(4):
        await cached_engine.search("query", source_id="github", token_budget=500)

    ratio = _sample_value(_fresh_metrics, "context_cache_hit_ratio", {})
    assert ratio == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_hit_ratio_all_misses(
    cached_engine: CachedHybridSearchEngine,
    _fresh_metrics: CollectorRegistry,
) -> None:
    """Ratio is 0.0 when all requests are cache misses."""
    for _ in range(4):
        await cached_engine.search("query", source_id="github", token_budget=500)

    ratio = _sample_value(_fresh_metrics, "context_cache_hit_ratio", {})
    assert ratio == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_hit_ratio_mixed_traffic(
    cached_engine: CachedHybridSearchEngine,
    mock_cache: AsyncMock,
    _fresh_metrics: CollectorRegistry,
) -> None:
    """Ratio equals hits / (hits + misses) after mixed cache traffic.

    Sequence: 2 misses, then 2 hits → expected ratio 0.5.
    """
    # 2 misses
    mock_cache.get = AsyncMock(return_value=None)
    for _ in range(2):
        await cached_engine.search("query", source_id="github", token_budget=500)

    # 2 hits
    mock_cache.get = AsyncMock(return_value=_make_chunks(2))
    for _ in range(2):
        await cached_engine.search("query", source_id="github", token_budget=500)

    ratio = _sample_value(_fresh_metrics, "context_cache_hit_ratio", {})
    assert ratio == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_hit_ratio_three_hits_one_miss(
    cached_engine: CachedHybridSearchEngine,
    mock_cache: AsyncMock,
    _fresh_metrics: CollectorRegistry,
) -> None:
    """Ratio is 0.75 for 3 hits and 1 miss."""
    # 1 miss
    mock_cache.get = AsyncMock(return_value=None)
    await cached_engine.search("query", source_id="github", token_budget=500)

    # 3 hits
    mock_cache.get = AsyncMock(return_value=_make_chunks(2))
    for _ in range(3):
        await cached_engine.search("query", source_id="github", token_budget=500)

    ratio = _sample_value(_fresh_metrics, "context_cache_hit_ratio", {})
    assert ratio == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Tests — multi-source counter isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_counters_labelled_by_source_id(
    cached_engine: CachedHybridSearchEngine,
    mock_cache: AsyncMock,
    _fresh_metrics: CollectorRegistry,
) -> None:
    """Each source_id has its own counter bucket."""
    mock_cache.get = AsyncMock(return_value=_make_chunks(2, source_id="jira"))

    await cached_engine.search("query", source_id="jira", token_budget=500)

    jira_hit = _sample_value(
        _fresh_metrics,
        "context_cache_requests_total",
        {"source_id": "jira", "result": "hit"},
    )
    github_hit = _sample_value(
        _fresh_metrics,
        "context_cache_requests_total",
        {"source_id": "github", "result": "hit"},
    )
    assert jira_hit == pytest.approx(1.0)
    assert github_hit is None or github_hit == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests — metrics present in /metrics scrape output
# ---------------------------------------------------------------------------


def test_metrics_present_in_scrape_output(_fresh_metrics: CollectorRegistry) -> None:
    """Both metrics are present in the Prometheus text exposition format."""
    output = generate_latest(_fresh_metrics).decode()

    assert "context_cache_requests_total" in output
    assert "context_cache_hit_ratio" in output
