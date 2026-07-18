"""Unit tests for RetrievedChunk US-017 compression fields: `compressed` and `original_token_count`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

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
# Default values
# ---------------------------------------------------------------------------


class TestCompressionDefaults:
    def test_compressed_defaults_to_false(self):
        chunk = _valid_chunk()
        assert chunk.compressed is False

    def test_original_token_count_defaults_to_none(self):
        chunk = _valid_chunk()
        assert chunk.original_token_count is None

    def test_construction_without_new_fields_succeeds(self):
        """Backward-compatibility: existing construction sites need no changes."""
        chunk = _valid_chunk()
        assert chunk.source_id == "github"
        assert chunk.compressed is False
        assert chunk.original_token_count is None


# ---------------------------------------------------------------------------
# model_copy round-trip (ChunkSummarizer contract)
# ---------------------------------------------------------------------------


class TestModelCopyRoundTrip:
    def test_model_copy_sets_compressed_and_token_count(self):
        chunk = _valid_chunk()
        summarised = chunk.model_copy(update={
            "content": "Summary of design document.",
            "compressed": True,
            "original_token_count": 800,
        })
        assert summarised.compressed is True
        assert summarised.original_token_count == 800
        assert summarised.content == "Summary of design document."

    def test_model_copy_preserves_identity_fields(self):
        chunk = _valid_chunk()
        summarised = chunk.model_copy(update={
            "content": "Summary.",
            "compressed": True,
            "original_token_count": 500,
        })
        assert summarised.chunk_id == chunk.chunk_id
        assert summarised.source_id == chunk.source_id
        assert summarised.score == chunk.score
        assert summarised.metadata == chunk.metadata
        assert summarised.vector_score == chunk.vector_score
        assert summarised.keyword_score == chunk.keyword_score

    def test_model_copy_produces_frozen_instance(self):
        chunk = _valid_chunk()
        summarised = chunk.model_copy(update={"compressed": True, "original_token_count": 300})
        with pytest.raises((ValueError, TypeError)):
            summarised.compressed = False  # type: ignore[misc]

    def test_original_chunk_unchanged_after_copy(self):
        chunk = _valid_chunk()
        _ = chunk.model_copy(update={"compressed": True, "original_token_count": 100})
        assert chunk.compressed is False
        assert chunk.original_token_count is None


# ---------------------------------------------------------------------------
# Valid field combinations
# ---------------------------------------------------------------------------


class TestValidFieldCombinations:
    def test_compressed_true_with_none_token_count_is_valid(self):
        """Chunk flagged as compressed but token count not yet recorded."""
        chunk = _valid_chunk(compressed=True, original_token_count=None)
        assert chunk.compressed is True
        assert chunk.original_token_count is None

    def test_compressed_false_with_none_token_count_is_valid(self):
        chunk = _valid_chunk(compressed=False, original_token_count=None)
        assert chunk.compressed is False
        assert chunk.original_token_count is None

    def test_compressed_true_with_token_count_is_valid(self):
        chunk = _valid_chunk(compressed=True, original_token_count=1024)
        assert chunk.compressed is True
        assert chunk.original_token_count == 1024

    def test_compressed_false_with_token_count_is_valid(self):
        """Unusual but not invalid — token count recorded even when not compressed."""
        chunk = _valid_chunk(compressed=False, original_token_count=512)
        assert chunk.compressed is False
        assert chunk.original_token_count == 512


# ---------------------------------------------------------------------------
# model_dump() serialisation (Kafka payload contract)
# ---------------------------------------------------------------------------


class TestModelDumpSerialisation:
    def test_model_dump_includes_compressed_field(self):
        chunk = _valid_chunk()
        data = chunk.model_dump()
        assert "compressed" in data
        assert data["compressed"] is False

    def test_model_dump_includes_original_token_count_field(self):
        chunk = _valid_chunk()
        data = chunk.model_dump()
        assert "original_token_count" in data
        assert data["original_token_count"] is None

    def test_model_dump_serialises_compressed_true(self):
        chunk = _valid_chunk(compressed=True, original_token_count=800)
        data = chunk.model_dump()
        assert data["compressed"] is True
        assert data["original_token_count"] == 800

    def test_model_dump_is_json_serialisable(self):
        chunk = _valid_chunk(compressed=True, original_token_count=400)
        data = chunk.model_dump()
        serialised = json.dumps(data, default=str)
        assert isinstance(serialised, str)

    def test_model_dump_json_roundtrip_preserves_values(self):
        chunk = _valid_chunk(compressed=True, original_token_count=350)
        data = chunk.model_dump()
        serialised = json.dumps(data, default=str)
        parsed = json.loads(serialised)
        assert parsed["compressed"] is True
        assert parsed["original_token_count"] == 350
