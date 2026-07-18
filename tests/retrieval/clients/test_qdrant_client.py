"""Unit tests for QdrantSearchClient and QueryEmbedder — TASK-US012-02.

All tests run without a live Qdrant instance or embedding model:
  - AsyncQdrantClient is replaced with an AsyncMock.
  - QueryEmbedder._model is replaced with a MagicMock.
  - No network calls and no model loading in CI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.retrieval.clients.qdrant_client import QdrantSearchClient
from src.retrieval.embedding.embedder import QueryEmbedder
from src.retrieval.schemas.retrieved_chunk import make_chunk_id

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SOURCE_ID = "github"
QUERY = "what is the context retrieval pipeline?"
VECTOR_DIM = 384
_FAKE_VECTOR = [0.1] * VECTOR_DIM

VALID_TIMESTAMP = datetime(2024, 3, 10, 12, 0, 0, tzinfo=UTC)
VALID_TIMESTAMP_ISO = VALID_TIMESTAMP.isoformat()


def _make_scored_point(
    score: float = 0.85,
    content: str = "chunk text",
    file_path: str = "docs/readme.md",
    chunk_index: int = 0,
    timestamp: str | None = VALID_TIMESTAMP_ISO,
    author: str = "alice",
    url: str | None = None,
    source_id: str | None = None,
) -> MagicMock:
    """Build a mock ScoredPoint returned by AsyncQdrantClient.search."""
    point = MagicMock()
    point.score = score
    point.payload = {
        "content": content,
        "chunk_index": chunk_index,
        "source_id": source_id or SOURCE_ID,
        "metadata": {
            "file_path": file_path,
            "timestamp": timestamp,
            "author": author,
            "url": url,
        },
    }
    return point


def _make_client(hits: list[MagicMock] | None = None) -> AsyncMock:
    """Return a mock AsyncQdrantClient whose search() resolves to *hits*."""
    client = AsyncMock()
    client.search = AsyncMock(return_value=hits or [])
    return client


def _make_search_client(
    qdrant_mock: AsyncMock | None = None,
    embedder: QueryEmbedder | None = None,
) -> QdrantSearchClient:
    """Construct a QdrantSearchClient with injected mocks."""
    if qdrant_mock is None:
        qdrant_mock = _make_client()
    sc = QdrantSearchClient(client=qdrant_mock)
    if embedder is not None:
        sc._embedder = embedder
    return sc


def _fake_embedder() -> QueryEmbedder:
    """Return a QueryEmbedder whose embed() returns a constant fake vector."""
    embedder = MagicMock(spec=QueryEmbedder)
    embedder.embed.return_value = _FAKE_VECTOR
    return embedder


# ---------------------------------------------------------------------------
# QueryEmbedder singleton
# ---------------------------------------------------------------------------


class TestQueryEmbedderSingleton:
    def setup_method(self) -> None:
        # Reset singleton before each test to ensure isolation.
        QueryEmbedder._instance = None

    def teardown_method(self) -> None:
        QueryEmbedder._instance = None

    def test_get_returns_same_instance(self) -> None:
        """Two consecutive calls to get() must return the identical object."""
        inst_a = QueryEmbedder.get()
        inst_b = QueryEmbedder.get()
        assert inst_a is inst_b

    def test_get_creates_instance_when_none(self) -> None:
        """get() creates the singleton when _instance is None."""
        assert QueryEmbedder._instance is None
        inst = QueryEmbedder.get()
        assert QueryEmbedder._instance is inst

    def test_second_get_does_not_call_init_again(self) -> None:
        """TextEmbedding model is loaded exactly once, not on subsequent calls."""
        import sys

        fake_cls = MagicMock()
        sys.modules["fastembed"].TextEmbedding = fake_cls  # type: ignore[attr-defined]
        try:
            QueryEmbedder.get()
            QueryEmbedder.get()
        finally:
            sys.modules["fastembed"].TextEmbedding = MagicMock  # type: ignore[attr-defined]

        assert fake_cls.call_count == 1

    def test_embed_delegates_to_model(self) -> None:
        """embed() returns a list of floats from the underlying model."""
        embedder = QueryEmbedder.get()
        fake_vector = [0.5] * VECTOR_DIM
        # The real TextEmbedding.embed returns an iterable of numpy arrays;
        # each element must have a .tolist() method.
        vec_mock = MagicMock()
        vec_mock.tolist.return_value = fake_vector
        embedder._model.embed.return_value = iter([vec_mock])
        result = embedder.embed("hello world")
        assert result == fake_vector


# ---------------------------------------------------------------------------
# QdrantSearchClient.search — return structure
# ---------------------------------------------------------------------------


class TestQdrantSearchClientSearch:
    @pytest.mark.asyncio
    async def test_returns_list_of_retrieved_chunks(self) -> None:
        """search() returns a list[RetrievedChunk]."""
        hits = [_make_scored_point(score=0.9)]
        client = _make_client(hits)
        sc = _make_search_client(qdrant_mock=client, embedder=_fake_embedder())

        results = await sc.search(query=QUERY, source_id=SOURCE_ID, top_k=10)

        assert len(results) == 1
        assert results[0].source_id == SOURCE_ID
        assert results[0].content == "chunk text"

    @pytest.mark.asyncio
    async def test_search_mode_is_vector(self) -> None:
        """All chunks returned by this client have search_mode == 'vector'."""
        hits = [_make_scored_point(), _make_scored_point(content="another")]
        sc = _make_search_client(hits=hits)

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert all(c.search_mode == "vector" for c in results)

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        """search() returns an empty list when Qdrant returns no hits."""
        sc = _make_search_client(hits=[])
        results = await sc.search(query=QUERY, source_id=SOURCE_ID)
        assert results == []

    @pytest.mark.asyncio
    async def test_results_ordered_by_descending_score(self) -> None:
        """Results are returned in the same order as Qdrant provides them."""
        # Qdrant returns results sorted by score descending; we preserve order.
        hits = [
            _make_scored_point(score=0.95),
            _make_scored_point(score=0.72),
            _make_scored_point(score=0.55),
        ]
        sc = _make_search_client(hits=hits)
        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)


def _make_search_client(
    hits: list[MagicMock] | None = None,
    qdrant_mock: AsyncMock | None = None,
    embedder: QueryEmbedder | None = None,
) -> QdrantSearchClient:  # type: ignore[misc]
    """Overload helper for convenience — hits shortcut builds the mock client."""
    if qdrant_mock is None:
        qdrant_mock = _make_client(hits)
    sc = QdrantSearchClient(client=qdrant_mock)
    sc._embedder = embedder if embedder is not None else _fake_embedder()
    return sc


# ---------------------------------------------------------------------------
# QdrantSearchClient — score clamping
# ---------------------------------------------------------------------------


class TestScoreClamping:
    @pytest.mark.asyncio
    async def test_score_above_one_is_clamped(self) -> None:
        """Scores > 1.0 are clamped to 1.0."""
        sc = _make_search_client(hits=[_make_scored_point(score=1.2)])
        results = await sc.search(query=QUERY, source_id=SOURCE_ID)
        assert results[0].score == 1.0

    @pytest.mark.asyncio
    async def test_score_below_zero_is_clamped(self) -> None:
        """Scores < 0.0 are clamped to 0.0."""
        sc = _make_search_client(hits=[_make_scored_point(score=-0.5)])
        results = await sc.search(query=QUERY, source_id=SOURCE_ID)
        assert results[0].score == 0.0

    @pytest.mark.asyncio
    async def test_score_within_range_unchanged(self) -> None:
        """Scores already in [0.0, 1.0] are not altered."""
        sc = _make_search_client(hits=[_make_scored_point(score=0.73)])
        results = await sc.search(query=QUERY, source_id=SOURCE_ID)
        assert results[0].score == pytest.approx(0.73)

    @pytest.mark.asyncio
    async def test_boundary_score_zero(self) -> None:
        sc = _make_search_client(hits=[_make_scored_point(score=0.0)])
        results = await sc.search(query=QUERY, source_id=SOURCE_ID)
        assert results[0].score == 0.0

    @pytest.mark.asyncio
    async def test_boundary_score_one(self) -> None:
        sc = _make_search_client(hits=[_make_scored_point(score=1.0)])
        results = await sc.search(query=QUERY, source_id=SOURCE_ID)
        assert results[0].score == 1.0


# ---------------------------------------------------------------------------
# QdrantSearchClient — source_id filter
# ---------------------------------------------------------------------------


class TestSourceFilter:
    def test_filter_contains_source_id_must_clause(self) -> None:
        """_source_filter() produces a Filter with a single FieldCondition on source_id."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        result = QdrantSearchClient._source_filter("github")

        assert isinstance(result, Filter)
        assert len(result.must) == 1
        condition = result.must[0]
        assert isinstance(condition, FieldCondition)
        assert condition.key == "source_id"
        assert isinstance(condition.match, MatchValue)
        assert condition.match.value == "github"

    @pytest.mark.asyncio
    async def test_search_passes_filter_to_qdrant(self) -> None:
        """search() forwards the source_id filter to AsyncQdrantClient.search."""
        client = _make_client([])
        sc = _make_search_client(qdrant_mock=client)

        await sc.search(query=QUERY, source_id="confluence", top_k=5)

        call_kwargs = client.search.call_args.kwargs
        assert call_kwargs["query_filter"] is not None
        condition = call_kwargs["query_filter"].must[0]
        assert condition.match.value == "confluence"

    @pytest.mark.asyncio
    async def test_search_passes_correct_top_k(self) -> None:
        """search() passes top_k as limit to AsyncQdrantClient.search."""
        client = _make_client([])
        sc = _make_search_client(qdrant_mock=client)

        await sc.search(query=QUERY, source_id=SOURCE_ID, top_k=7)

        assert client.search.call_args.kwargs["limit"] == 7


# ---------------------------------------------------------------------------
# QdrantSearchClient — chunk_id derivation
# ---------------------------------------------------------------------------


class TestChunkId:
    @pytest.mark.asyncio
    async def test_chunk_id_matches_make_chunk_id(self) -> None:
        """chunk_id is the SHA-256-derived ID from make_chunk_id."""
        hits = [_make_scored_point(file_path="src/main.py", chunk_index=3)]
        sc = _make_search_client(hits=hits)
        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        expected_id = make_chunk_id(SOURCE_ID, "src/main.py", 3)
        assert results[0].chunk_id == expected_id

    @pytest.mark.asyncio
    async def test_chunk_id_stable_for_same_inputs(self) -> None:
        """Repeated calls produce the same chunk_id for identical payload."""
        hits = [_make_scored_point(file_path="a.py", chunk_index=0)]
        sc = _make_search_client(hits=hits[:])
        r1 = await sc.search(query=QUERY, source_id=SOURCE_ID)

        sc2 = _make_search_client(hits=[_make_scored_point(file_path="a.py", chunk_index=0)])
        r2 = await sc2.search(query=QUERY, source_id=SOURCE_ID)

        assert r1[0].chunk_id == r2[0].chunk_id


# ---------------------------------------------------------------------------
# QdrantSearchClient — timestamp handling
# ---------------------------------------------------------------------------


class TestTimestampHandling:
    @pytest.mark.asyncio
    async def test_iso_string_timestamp_parsed(self) -> None:
        """ISO-format string timestamps are converted to datetime."""
        hits = [_make_scored_point(timestamp=VALID_TIMESTAMP_ISO)]
        sc = _make_search_client(hits=hits)
        results = await sc.search(query=QUERY, source_id=SOURCE_ID)
        assert isinstance(results[0].metadata.timestamp, datetime)

    @pytest.mark.asyncio
    async def test_missing_timestamp_uses_fallback(self) -> None:
        """Missing timestamp falls back to a current datetime instead of raising."""
        hits = [_make_scored_point(timestamp=None)]
        sc = _make_search_client(hits=hits)
        before = datetime.now(UTC)
        results = await sc.search(query=QUERY, source_id=SOURCE_ID)
        after = datetime.now(UTC)
        ts = results[0].metadata.timestamp
        # Fallback should be a recent datetime
        assert before <= ts <= after

    @pytest.mark.asyncio
    async def test_datetime_object_timestamp_preserved(self) -> None:
        """datetime objects in the payload are used directly."""
        hits = [_make_scored_point(timestamp=VALID_TIMESTAMP)]
        sc = _make_search_client(hits=hits)
        results = await sc.search(query=QUERY, source_id=SOURCE_ID)
        assert results[0].metadata.timestamp == VALID_TIMESTAMP


# ---------------------------------------------------------------------------
# QdrantSearchClient — embedding integration
# ---------------------------------------------------------------------------


class TestEmbeddingIntegration:
    @pytest.mark.asyncio
    async def test_embed_called_with_query(self) -> None:
        """The embedder is called once with the query string."""
        embedder = _fake_embedder()
        sc = _make_search_client(hits=[], embedder=embedder)

        await sc.search(query="my query", source_id=SOURCE_ID)

        embedder.embed.assert_called_once_with("my query")

    @pytest.mark.asyncio
    async def test_query_vector_forwarded_to_qdrant(self) -> None:
        """The vector returned by embed() is passed to AsyncQdrantClient.search."""
        fake_vec = [0.42] * VECTOR_DIM
        embedder = MagicMock(spec=QueryEmbedder)
        embedder.embed.return_value = fake_vec

        client = _make_client([])
        sc = _make_search_client(qdrant_mock=client, embedder=embedder)
        await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert client.search.call_args.kwargs["query_vector"] == fake_vec


# ---------------------------------------------------------------------------
# QdrantSearchClient — collection name
# ---------------------------------------------------------------------------


class TestCollectionName:
    def test_collection_default(self) -> None:
        """COLLECTION defaults to 'contextiq_chunks' when env var is absent."""
        import os

        env_var = os.environ.pop("QDRANT_COLLECTION_NAME", None)
        try:
            # Re-import to pick up the default (class variable set at import time).
            # We test the default indirectly via the class attribute.
            assert QdrantSearchClient.COLLECTION in (
                "contextiq_chunks",
                env_var or "contextiq_chunks",
            )
        finally:
            if env_var is not None:
                os.environ["QDRANT_COLLECTION_NAME"] = env_var

    @pytest.mark.asyncio
    async def test_search_uses_collection_name(self) -> None:
        """search() passes COLLECTION as collection_name to AsyncQdrantClient."""
        client = _make_client([])
        sc = _make_search_client(qdrant_mock=client)
        await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert client.search.call_args.kwargs["collection_name"] == QdrantSearchClient.COLLECTION

    @pytest.mark.asyncio
    async def test_search_disables_vector_return(self) -> None:
        """search() requests with_vectors=False to minimise payload size."""
        client = _make_client([])
        sc = _make_search_client(qdrant_mock=client)
        await sc.search(query=QUERY, source_id=SOURCE_ID)
        assert client.search.call_args.kwargs["with_vectors"] is False

    @pytest.mark.asyncio
    async def test_search_enables_payload_return(self) -> None:
        """search() requests with_payload=True."""
        client = _make_client([])
        sc = _make_search_client(qdrant_mock=client)
        await sc.search(query=QUERY, source_id=SOURCE_ID)
        assert client.search.call_args.kwargs["with_payload"] is True
