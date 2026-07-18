"""Unit tests for OpenSearchSearchClient — TASK-US012-03.

All tests run without a live OpenSearch instance:
  - AsyncOpenSearch is replaced with an AsyncMock.
  - No network calls in CI.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.retrieval.clients.opensearch_client import (
    OpenSearchSearchClient,
    _normalise_bm25,
)
from src.retrieval.schemas.retrieved_chunk import make_chunk_id

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_ID = "confluence"
QUERY = "what is the context retrieval pipeline?"
VALID_TIMESTAMP = datetime(2024, 3, 10, 12, 0, 0, tzinfo=UTC)
VALID_TIMESTAMP_ISO = VALID_TIMESTAMP.isoformat()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hit(
    score: float = 8.5,
    content: str = "chunk text",
    file_path: str = "docs/readme.md",
    chunk_index: int = 0,
    timestamp: str | datetime | None = VALID_TIMESTAMP_ISO,
    author: str = "alice",
    url: str | None = None,
    source_id: str = SOURCE_ID,
) -> dict:
    """Build a mock OpenSearch hit dict."""
    return {
        "_score": score,
        "_source": {
            "content": content,
            "source_id": source_id,
            "metadata": {
                "file_path": file_path,
                "chunk_index": chunk_index,
                "timestamp": timestamp,
                "author": author,
                "url": url,
            },
        },
    }


def _make_response(
    hits: list[dict] | None = None,
    max_score: float | None = 8.5,
) -> dict:
    """Build a mock OpenSearch search response envelope."""
    return {
        "hits": {
            "total": {"value": len(hits or [])},
            "max_score": max_score,
            "hits": hits or [],
        }
    }


def _make_async_client(response: dict | None = None) -> AsyncMock:
    """Return a mock AsyncOpenSearch whose search() resolves to *response*."""
    client = AsyncMock()
    client.search = AsyncMock(return_value=response or _make_response())
    return client


def _make_search_client(
    async_client: AsyncMock | None = None,
) -> OpenSearchSearchClient:
    """Construct an OpenSearchSearchClient with an injected mock."""
    if async_client is None:
        async_client = _make_async_client()
    return OpenSearchSearchClient(client=async_client)


# ---------------------------------------------------------------------------
# _normalise_bm25 — pure function
# ---------------------------------------------------------------------------


class TestNormaliseBm25:
    def test_normal_score_below_max(self) -> None:
        assert _normalise_bm25(4.0, 8.0) == pytest.approx(0.5)

    def test_score_equals_max(self) -> None:
        assert _normalise_bm25(8.0, 8.0) == pytest.approx(1.0)

    def test_score_exceeds_max_clamped_to_one(self) -> None:
        """Should never happen in practice, but guard against it."""
        assert _normalise_bm25(10.0, 8.0) == pytest.approx(1.0)

    def test_zero_max_score_returns_zero(self) -> None:
        """Guard against division by zero when max_score is 0."""
        assert _normalise_bm25(5.0, 0.0) == 0.0

    def test_zero_score_zero_max_returns_zero(self) -> None:
        assert _normalise_bm25(0.0, 0.0) == 0.0

    def test_zero_score_nonzero_max_returns_zero(self) -> None:
        assert _normalise_bm25(0.0, 10.0) == pytest.approx(0.0)

    def test_result_is_bounded_above(self) -> None:
        result = _normalise_bm25(100.0, 1.0)
        assert result <= 1.0


# ---------------------------------------------------------------------------
# OpenSearchSearchClient.search — return structure
# ---------------------------------------------------------------------------


class TestOpenSearchClientSearch:
    @pytest.mark.asyncio
    async def test_returns_list_of_retrieved_chunks(self) -> None:
        """search() returns a list[RetrievedChunk]."""
        hits = [_make_hit(score=8.5)]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID, top_k=10)

        assert len(results) == 1
        assert results[0].source_id == SOURCE_ID
        assert results[0].content == "chunk text"

    @pytest.mark.asyncio
    async def test_search_mode_is_keyword(self) -> None:
        """All chunks returned by this client have search_mode == 'keyword'."""
        hits = [_make_hit(), _make_hit(content="other chunk")]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert all(c.search_mode == "keyword" for c in results)

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        """search() returns an empty list when OpenSearch returns no hits."""
        response = _make_response(hits=[], max_score=None)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results == []

    @pytest.mark.asyncio
    async def test_results_ordered_by_descending_score(self) -> None:
        """Results preserve the order returned by OpenSearch (descending BM25)."""
        hits = [
            _make_hit(score=9.0),
            _make_hit(score=6.5),
            _make_hit(score=3.0),
        ]
        response = _make_response(hits=hits, max_score=9.0)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_multiple_chunks_different_scores(self) -> None:
        hits = [
            _make_hit(score=10.0, content="best match"),
            _make_hit(score=5.0, content="decent match"),
        ]
        response = _make_response(hits=hits, max_score=10.0)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert len(results) == 2
        assert results[0].score == pytest.approx(1.0)
        assert results[1].score == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# BM25 score normalisation
# ---------------------------------------------------------------------------


class TestBm25ScoreNormalisation:
    @pytest.mark.asyncio
    async def test_top_score_normalises_to_one(self) -> None:
        """The highest-scoring chunk should receive score == 1.0."""
        hits = [_make_hit(score=12.0)]
        response = _make_response(hits=hits, max_score=12.0)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_partial_score_normalised_correctly(self) -> None:
        """A hit with score 6.0 when max is 12.0 should yield 0.5."""
        hits = [_make_hit(score=6.0)]
        response = _make_response(hits=hits, max_score=12.0)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].score == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_score_zero_when_max_score_absent(self) -> None:
        """When max_score is None (empty result), guard defaults to 1.0 divisor."""
        hits = [_make_hit(score=0.0)]
        response = _make_response(hits=hits, max_score=None)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_score_zero_when_max_score_is_zero(self) -> None:
        """When max_score is explicitly 0.0, all scores normalise to 0.0."""
        hits = [_make_hit(score=5.0)]
        # Force max_score to 0 — simulates degenerate response
        response = {
            "hits": {
                "total": {"value": 1},
                "max_score": 0.0,
                "hits": hits,
            }
        }
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].score == 0.0

    @pytest.mark.asyncio
    async def test_all_scores_in_range(self) -> None:
        """All normalised scores are within [0.0, 1.0]."""
        hits = [_make_hit(score=s) for s in [1.0, 5.0, 10.0, 7.3]]
        response = _make_response(hits=hits, max_score=10.0)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        for chunk in results:
            assert 0.0 <= chunk.score <= 1.0


# ---------------------------------------------------------------------------
# source_id filter in query
# ---------------------------------------------------------------------------


class TestSourceIdFilter:
    @pytest.mark.asyncio
    async def test_filter_clause_contains_source_id(self) -> None:
        """_build_query must include a filter term for source_id."""
        query_dict = OpenSearchSearchClient._build_query(QUERY, SOURCE_ID, 20)

        filters = query_dict["query"]["bool"]["filter"]
        assert any(f.get("term", {}).get("source_id") == SOURCE_ID for f in filters)

    @pytest.mark.asyncio
    async def test_search_passes_source_id_in_filter(self) -> None:
        """search() calls OpenSearch with a query that filters by source_id."""
        async_client = _make_async_client(_make_response())
        sc = _make_search_client(async_client)

        await sc.search(query=QUERY, source_id=SOURCE_ID)

        call_kwargs = async_client.search.call_args[1]
        body = call_kwargs["body"]
        filters = body["query"]["bool"]["filter"]
        assert any(f.get("term", {}).get("source_id") == SOURCE_ID for f in filters)

    def test_build_query_includes_multi_match(self) -> None:
        """_build_query must include a multi_match on content and metadata.file_path."""
        query_dict = OpenSearchSearchClient._build_query(QUERY, SOURCE_ID, 10)

        must_clauses = query_dict["query"]["bool"]["must"]
        multi_match = next(
            (c["multi_match"] for c in must_clauses if "multi_match" in c), None
        )
        assert multi_match is not None
        assert "content^2" in multi_match["fields"]
        assert "metadata.file_path" in multi_match["fields"]
        assert multi_match["query"] == QUERY

    def test_build_query_respects_top_k(self) -> None:
        """_build_query must set size to top_k."""
        for top_k in (5, 20, 100):
            query_dict = OpenSearchSearchClient._build_query(QUERY, SOURCE_ID, top_k)
            assert query_dict["size"] == top_k


# ---------------------------------------------------------------------------
# Chunk ID generation
# ---------------------------------------------------------------------------


class TestChunkId:
    @pytest.mark.asyncio
    async def test_chunk_id_is_content_addressable(self) -> None:
        """chunk_id must match make_chunk_id(source_id, file_path, chunk_index)."""
        file_path = "docs/readme.md"
        chunk_index = 3
        hits = [_make_hit(file_path=file_path, chunk_index=chunk_index)]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        expected_id = make_chunk_id(SOURCE_ID, file_path, chunk_index)
        assert results[0].chunk_id == expected_id

    @pytest.mark.asyncio
    async def test_chunk_id_differs_for_different_indexes(self) -> None:
        """Two chunks with different chunk_index values produce different IDs."""
        hits = [
            _make_hit(chunk_index=0, file_path="f.md"),
            _make_hit(chunk_index=1, file_path="f.md"),
        ]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].chunk_id != results[1].chunk_id


# ---------------------------------------------------------------------------
# Metadata mapping
# ---------------------------------------------------------------------------


class TestMetadataMapping:
    @pytest.mark.asyncio
    async def test_file_path_mapped(self) -> None:
        hits = [_make_hit(file_path="notes/design.md")]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].metadata.file_path == "notes/design.md"

    @pytest.mark.asyncio
    async def test_author_mapped(self) -> None:
        hits = [_make_hit(author="bob")]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].metadata.author == "bob"

    @pytest.mark.asyncio
    async def test_url_optional_none(self) -> None:
        hits = [_make_hit(url=None)]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].metadata.url is None

    @pytest.mark.asyncio
    async def test_url_mapped_when_present(self) -> None:
        hits = [_make_hit(url="https://example.com/page")]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].metadata.url == "https://example.com/page"

    @pytest.mark.asyncio
    async def test_chunk_index_mapped(self) -> None:
        hits = [_make_hit(chunk_index=7)]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].metadata.chunk_index == 7

    @pytest.mark.asyncio
    async def test_timestamp_parsed_from_iso_string(self) -> None:
        hits = [_make_hit(timestamp=VALID_TIMESTAMP_ISO)]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].metadata.timestamp == VALID_TIMESTAMP

    @pytest.mark.asyncio
    async def test_timestamp_passthrough_when_datetime(self) -> None:
        hits = [_make_hit(timestamp=VALID_TIMESTAMP)]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].metadata.timestamp == VALID_TIMESTAMP

    @pytest.mark.asyncio
    async def test_timestamp_defaults_to_now_when_absent(self) -> None:
        before = datetime.now(UTC)
        hits = [_make_hit(timestamp=None)]
        response = _make_response(hits=hits, max_score=8.5)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        after = datetime.now(UTC)
        assert before <= results[0].metadata.timestamp <= after

    @pytest.mark.asyncio
    async def test_missing_metadata_uses_defaults(self) -> None:
        """Hits without a metadata key should not raise."""
        hit = {
            "_score": 5.0,
            "_source": {
                "content": "bare content",
                "source_id": SOURCE_ID,
            },
        }
        response = _make_response(hits=[hit], max_score=5.0)
        sc = _make_search_client(_make_async_client(response))

        results = await sc.search(query=QUERY, source_id=SOURCE_ID)

        assert results[0].content == "bare content"
        assert results[0].metadata.file_path == ""
        assert results[0].metadata.chunk_index == 0


# ---------------------------------------------------------------------------
# INDEX class attribute
# ---------------------------------------------------------------------------


class TestIndexAttribute:
    def test_default_index_name(self) -> None:
        """INDEX defaults to 'contextiq_chunks' when env var is absent."""
        env_var = os.environ.pop("OPENSEARCH_INDEX_NAME", None)
        try:
            # Reload module to pick up env change
            import importlib

            import src.retrieval.clients.opensearch_client as mod

            importlib.reload(mod)
            assert mod.OpenSearchSearchClient.INDEX == "contextiq_chunks"
        finally:
            if env_var is not None:
                os.environ["OPENSEARCH_INDEX_NAME"] = env_var
            import importlib

            import src.retrieval.clients.opensearch_client as mod

            importlib.reload(mod)

    def test_index_name_from_env(self) -> None:
        """INDEX reads from OPENSEARCH_INDEX_NAME when set."""
        os.environ["OPENSEARCH_INDEX_NAME"] = "my_custom_index"
        try:
            import importlib

            import src.retrieval.clients.opensearch_client as mod

            importlib.reload(mod)
            assert mod.OpenSearchSearchClient.INDEX == "my_custom_index"
        finally:
            del os.environ["OPENSEARCH_INDEX_NAME"]
            import importlib

            import src.retrieval.clients.opensearch_client as mod

            importlib.reload(mod)

    @pytest.mark.asyncio
    async def test_search_uses_index_attribute(self) -> None:
        """search() passes INDEX as the index parameter to AsyncOpenSearch.search."""
        async_client = _make_async_client(_make_response())
        sc = _make_search_client(async_client)
        sc.INDEX = "test_index"  # type: ignore[assignment]

        await sc.search(query=QUERY, source_id=SOURCE_ID)

        call_kwargs = async_client.search.call_args[1]
        assert call_kwargs["index"] == "test_index"
