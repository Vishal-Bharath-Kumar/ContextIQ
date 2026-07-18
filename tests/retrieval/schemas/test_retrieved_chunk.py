"""Unit tests for RetrievedChunk, ChunkMetadata, and make_chunk_id."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from src.retrieval.schemas.retrieved_chunk import (
    ChunkMetadata,
    RetrievedChunk,
    make_chunk_id,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_METADATA = ChunkMetadata(
    file_path="docs/design.md",
    timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
    author="alice",
)


def _valid_chunk(**overrides: Any) -> RetrievedChunk:
    chunk_id = make_chunk_id("github", "docs/design.md", 0)
    defaults: dict[str, Any] = {
        "chunk_id": chunk_id,
        "source_id": "github",
        "content": "Design document content.",
        "score": 0.85,
        "metadata": VALID_METADATA,
        "search_mode": "vector",
    }
    defaults.update(overrides)
    return RetrievedChunk(**defaults)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestRetrievedChunkConstruction:
    def test_valid_construction(self):
        chunk = _valid_chunk()
        assert chunk.source_id == "github"
        assert chunk.content == "Design document content."
        assert chunk.score == 0.85
        assert chunk.search_mode == "vector"

    def test_default_search_mode_is_rrf(self):
        chunk = _valid_chunk(search_mode="rrf")
        assert chunk.search_mode == "rrf"

    def test_search_mode_keyword(self):
        chunk = _valid_chunk(search_mode="keyword")
        assert chunk.search_mode == "keyword"

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            RetrievedChunk(
                chunk_id="abc",
                source_id="github",
                # content missing
                score=0.5,
                metadata=VALID_METADATA,
            )


# ---------------------------------------------------------------------------
# Score boundary validation
# ---------------------------------------------------------------------------


class TestScoreBoundaries:
    def test_score_zero_is_valid(self):
        chunk = _valid_chunk(score=0.0)
        assert chunk.score == 0.0

    def test_score_one_is_valid(self):
        chunk = _valid_chunk(score=1.0)
        assert chunk.score == 1.0

    def test_score_below_zero_raises(self):
        with pytest.raises(ValidationError):
            _valid_chunk(score=-0.01)

    def test_score_above_one_raises(self):
        with pytest.raises(ValidationError):
            _valid_chunk(score=1.001)


# ---------------------------------------------------------------------------
# ChunkMetadata required fields
# ---------------------------------------------------------------------------


class TestChunkMetadata:
    def test_required_fields_present(self):
        meta = ChunkMetadata(
            file_path="src/main.py",
            timestamp=datetime(2024, 6, 1, tzinfo=UTC),
            author="bob",
        )
        assert meta.file_path == "src/main.py"
        assert meta.author == "bob"

    def test_optional_url_defaults_none(self):
        meta = ChunkMetadata(
            file_path="src/main.py",
            timestamp=datetime(2024, 6, 1, tzinfo=UTC),
            author="bob",
        )
        assert meta.url is None

    def test_optional_chunk_index_defaults_none(self):
        meta = ChunkMetadata(
            file_path="src/main.py",
            timestamp=datetime(2024, 6, 1, tzinfo=UTC),
            author="bob",
        )
        assert meta.chunk_index is None

    def test_missing_file_path_raises(self):
        with pytest.raises(ValidationError):
            ChunkMetadata(
                timestamp=datetime(2024, 6, 1, tzinfo=UTC),
                author="bob",
            )

    def test_missing_timestamp_raises(self):
        with pytest.raises(ValidationError):
            ChunkMetadata(file_path="src/main.py", author="bob")

    def test_missing_author_raises(self):
        with pytest.raises(ValidationError):
            ChunkMetadata(
                file_path="src/main.py",
                timestamp=datetime(2024, 6, 1, tzinfo=UTC),
            )


# ---------------------------------------------------------------------------
# model_dump() round-trip
# ---------------------------------------------------------------------------


class TestModelDumpRoundTrip:
    def test_model_dump_returns_json_compatible_dict(self):
        chunk = _valid_chunk()
        data = chunk.model_dump()
        # Verify JSON serialisation succeeds (all types are primitives / ISO strings)
        serialised = json.dumps(data, default=str)
        assert isinstance(serialised, str)

    def test_model_dump_contains_expected_keys(self):
        chunk = _valid_chunk()
        data = chunk.model_dump()
        assert set(data.keys()) == {
            "chunk_id",
            "source_id",
            "content",
            "score",
            "metadata",
            "search_mode",
            "vector_score",
            "keyword_score",
            "compressed",
            "original_token_count",
        }

    def test_metadata_nested_in_dump(self):
        chunk = _valid_chunk()
        data = chunk.model_dump()
        assert "file_path" in data["metadata"]
        assert "author" in data["metadata"]


# ---------------------------------------------------------------------------
# Immutability (frozen=True)
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_mutation_raises(self):
        chunk = _valid_chunk()
        with pytest.raises((ValidationError, TypeError)):
            chunk.score = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# make_chunk_id determinism
# ---------------------------------------------------------------------------


class TestMakeChunkId:
    def test_deterministic(self):
        id1 = make_chunk_id("github", "docs/design.md", 3)
        id2 = make_chunk_id("github", "docs/design.md", 3)
        assert id1 == id2

    def test_different_inputs_produce_different_ids(self):
        id1 = make_chunk_id("github", "docs/design.md", 0)
        id2 = make_chunk_id("github", "docs/design.md", 1)
        assert id1 != id2

    def test_different_sources_produce_different_ids(self):
        id1 = make_chunk_id("github", "docs/design.md", 0)
        id2 = make_chunk_id("confluence", "docs/design.md", 0)
        assert id1 != id2

    def test_output_is_16_hex_chars(self):
        chunk_id = make_chunk_id("github", "docs/design.md", 0)
        assert len(chunk_id) == 16
        assert all(c in "0123456789abcdef" for c in chunk_id)
