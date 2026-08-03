"""Unit tests for ChunkRecord ORM and Pydantic schemas — TASK-US027-01.

All tests run without a database connection; ORM tests assert in-memory
object construction, schema tests assert Pydantic validation behaviour and
frozen-model constraints.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.indexing.models.chunk import ChunkRecord
from src.indexing.schemas.chunk import ChunkMetadata, ChunkPayload, IndexedChunk

NOW = datetime(2026, 7, 16, 0, 0, 0, tzinfo=timezone.utc)
SOURCE_ID = uuid4()
CHUNK_ID = uuid4()


# ---------------------------------------------------------------------------
# ChunkRecord ORM — no DB required
# ---------------------------------------------------------------------------


class TestChunkRecord:
    def test_instantiation_minimal(self) -> None:
        record = ChunkRecord(
            chunk_id=CHUNK_ID,
            source_id=SOURCE_ID,
            tenant_id="acme",
            document_id="github:owner/repo:abc123",
            embedding_model="text-embedding-3-small",
            token_count=128,
        )
        assert record.chunk_id == CHUNK_ID
        assert record.source_id == SOURCE_ID
        assert record.tenant_id == "acme"
        assert record.document_id == "github:owner/repo:abc123"
        assert record.embedding_model == "text-embedding-3-small"
        assert record.token_count == 128

    def test_indexed_at_nullable_before_db_flush(self) -> None:
        record = ChunkRecord(
            chunk_id=uuid4(),
            source_id=SOURCE_ID,
            tenant_id="acme",
            document_id="jira:PROJ-1",
            embedding_model="text-embedding-3-small",
            token_count=64,
        )
        # server_default is applied by the DB; Python-side value is None
        assert record.indexed_at is None

    def test_tablename(self) -> None:
        assert ChunkRecord.__tablename__ == "chunk_index"


# ---------------------------------------------------------------------------
# ChunkPayload — validation
# ---------------------------------------------------------------------------


class TestChunkPayload:
    def test_valid_minimal(self) -> None:
        payload = ChunkPayload(
            source_id=SOURCE_ID,
            tenant_id="acme",
            document_id="github:owner/repo:abc123",
            text="The quick brown fox",
            token_count=5,
        )
        assert isinstance(payload.chunk_id, UUID)
        assert payload.token_count == 5
        assert payload.metadata == {}

    def test_default_chunk_id_generated(self) -> None:
        p1 = ChunkPayload(
            source_id=SOURCE_ID,
            tenant_id="acme",
            document_id="doc:1",
            text="text",
            token_count=1,
        )
        p2 = ChunkPayload(
            source_id=SOURCE_ID,
            tenant_id="acme",
            document_id="doc:1",
            text="text",
            token_count=1,
        )
        assert p1.chunk_id != p2.chunk_id

    def test_frozen_model_rejects_mutation(self) -> None:
        payload = ChunkPayload(
            source_id=SOURCE_ID,
            tenant_id="acme",
            document_id="doc:1",
            text="immutable",
            token_count=1,
        )
        with pytest.raises((TypeError, ValidationError)):
            payload.text = "mutated"  # type: ignore[misc]

    def test_empty_text_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChunkPayload(
                source_id=SOURCE_ID,
                tenant_id="acme",
                document_id="doc:1",
                text="",
                token_count=1,
            )

    def test_zero_token_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChunkPayload(
                source_id=SOURCE_ID,
                tenant_id="acme",
                document_id="doc:1",
                text="text",
                token_count=0,
            )

    def test_tenant_id_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ChunkPayload(
                source_id=SOURCE_ID,
                tenant_id="x" * 129,
                document_id="doc:1",
                text="text",
                token_count=1,
            )

    def test_document_id_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ChunkPayload(
                source_id=SOURCE_ID,
                tenant_id="acme",
                document_id="d" * 513,
                text="text",
                token_count=1,
            )

    def test_metadata_custom_dict(self) -> None:
        payload = ChunkPayload(
            source_id=SOURCE_ID,
            tenant_id="acme",
            document_id="doc:1",
            text="text",
            token_count=1,
            metadata={"page": 3, "section": "intro"},
        )
        assert payload.metadata["page"] == 3


# ---------------------------------------------------------------------------
# ChunkMetadata — validation
# ---------------------------------------------------------------------------


class TestChunkMetadata:
    def test_valid(self) -> None:
        meta = ChunkMetadata(
            chunk_id=CHUNK_ID,
            source_id=SOURCE_ID,
            tenant_id="acme",
            document_id="github:owner/repo:abc123",
            embedding_model="text-embedding-3-small",
            token_count=128,
            indexed_at=NOW,
        )
        assert meta.chunk_id == CHUNK_ID
        assert meta.indexed_at == NOW

    def test_frozen(self) -> None:
        meta = ChunkMetadata(
            chunk_id=CHUNK_ID,
            source_id=SOURCE_ID,
            tenant_id="acme",
            document_id="doc:1",
            embedding_model="model",
            token_count=1,
            indexed_at=NOW,
        )
        with pytest.raises((TypeError, ValidationError)):
            meta.token_count = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# IndexedChunk — validation
# ---------------------------------------------------------------------------


class TestIndexedChunk:
    def test_valid(self) -> None:
        payload = ChunkPayload(
            source_id=SOURCE_ID,
            tenant_id="acme",
            document_id="doc:1",
            text="some text",
            token_count=2,
        )
        chunk = IndexedChunk(
            payload=payload,
            vector=[0.1, 0.2, 0.3],
            model_id="text-embedding-3-small",
        )
        assert chunk.vector == [0.1, 0.2, 0.3]
        assert chunk.model_id == "text-embedding-3-small"

    def test_frozen(self) -> None:
        payload = ChunkPayload(
            source_id=SOURCE_ID,
            tenant_id="acme",
            document_id="doc:1",
            text="text",
            token_count=1,
        )
        chunk = IndexedChunk(payload=payload, vector=[0.0], model_id="m")
        with pytest.raises((TypeError, ValidationError)):
            chunk.model_id = "other"  # type: ignore[misc]
