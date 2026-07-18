"""Unit tests for RemovedChunk schema (TASK-US015-01)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.compression.schemas.removed_chunk import RemovalReason, RemovedChunk


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _exact_dup_chunk() -> RemovedChunk:
    return RemovedChunk(
        chunk_id="abc123",
        source_id="github",
        reason=RemovalReason.EXACT_DUPLICATE,
        duplicate_of="xyz789",
        original_content="def foo(): pass",
    )


def _boilerplate_chunk() -> RemovedChunk:
    return RemovedChunk(
        chunk_id="def456",
        source_id="confluence",
        reason=RemovalReason.BOILERPLATE,
        boilerplate_rule="copyright_header",
        original_content="Copyright (c) 2024 Acme Corp. All rights reserved.",
    )


def _semantic_near_dup_chunk() -> RemovedChunk:
    return RemovedChunk(
        chunk_id="ghi000",
        source_id="jira",
        reason=RemovalReason.SEMANTIC_NEAR_DUP,
        duplicate_of="abc123",
        original_content="def foo(): pass  # near-duplicate",
    )


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------


class TestRemovedChunkConstruction:
    def test_exact_duplicate_construction(self) -> None:
        chunk = _exact_dup_chunk()
        assert chunk.chunk_id == "abc123"
        assert chunk.source_id == "github"
        assert chunk.reason == RemovalReason.EXACT_DUPLICATE
        assert chunk.duplicate_of == "xyz789"
        assert chunk.boilerplate_rule is None
        assert chunk.original_content == "def foo(): pass"

    def test_boilerplate_construction(self) -> None:
        chunk = _boilerplate_chunk()
        assert chunk.reason == RemovalReason.BOILERPLATE
        assert chunk.boilerplate_rule == "copyright_header"
        assert chunk.duplicate_of is None

    def test_semantic_near_dup_construction(self) -> None:
        chunk = _semantic_near_dup_chunk()
        assert chunk.reason == RemovalReason.SEMANTIC_NEAR_DUP
        assert chunk.duplicate_of == "abc123"


# ---------------------------------------------------------------------------
# model_dump / serialisation
# ---------------------------------------------------------------------------


class TestRemovedChunkSerialisation:
    def test_model_dump_is_json_compatible(self) -> None:
        data = _exact_dup_chunk().model_dump()
        assert isinstance(data, dict)
        assert data["chunk_id"] == "abc123"
        assert data["reason"] == "exact_duplicate"
        assert data["original_content"] == "def foo(): pass"
        assert data["duplicate_of"] == "xyz789"
        assert data["boilerplate_rule"] is None

    def test_original_content_present_in_dump(self) -> None:
        chunk = _boilerplate_chunk()
        dumped = chunk.model_dump()
        assert "original_content" in dumped
        assert dumped["original_content"] == chunk.original_content

    def test_model_dump_round_trip(self) -> None:
        chunk = _exact_dup_chunk()
        restored = RemovedChunk.model_validate(chunk.model_dump())
        assert restored == chunk


# ---------------------------------------------------------------------------
# Immutability (frozen=True)
# ---------------------------------------------------------------------------


class TestRemovedChunkImmutability:
    def test_mutation_raises_validation_error(self) -> None:
        chunk = _exact_dup_chunk()
        with pytest.raises(ValidationError):
            chunk.chunk_id = "mutated"  # type: ignore[misc]

    def test_mutation_of_reason_raises(self) -> None:
        chunk = _boilerplate_chunk()
        with pytest.raises(ValidationError):
            chunk.reason = RemovalReason.EXACT_DUPLICATE  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RemovalReason enum values
# ---------------------------------------------------------------------------


class TestRemovalReason:
    def test_string_values(self) -> None:
        assert RemovalReason.EXACT_DUPLICATE == "exact_duplicate"
        assert RemovalReason.BOILERPLATE == "boilerplate"
        assert RemovalReason.SEMANTIC_NEAR_DUP == "semantic_near_dup"

    def test_all_three_reasons_distinct(self) -> None:
        reasons = {RemovalReason.EXACT_DUPLICATE, RemovalReason.BOILERPLATE, RemovalReason.SEMANTIC_NEAR_DUP}
        assert len(reasons) == 3
