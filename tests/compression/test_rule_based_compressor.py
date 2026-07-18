"""Unit tests for RuleBasedCompressor (TASK-US015-04)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from src.compression.rule_based_compressor import RuleBasedCompressor
from src.compression.schemas.removed_chunk import RemovalReason
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime(2024, 1, 1, tzinfo=UTC)

_LICENSE_HEADER = "// SPDX-License-Identifier: MIT\n// Copyright (c) 2024 ACME Corp\n"


def _meta(file_path: str = "src/mod.py") -> ChunkMetadata:
    return ChunkMetadata(file_path=file_path, timestamp=_TS, author="dev")


def _chunk(
    chunk_id: str,
    content: str,
    source_id: str = "github",
    score: float = 0.9,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        content=content,
        score=score,
        search_mode="rrf",
        metadata=_meta(),
    )


# ---------------------------------------------------------------------------
# AC-1: empty input
# ---------------------------------------------------------------------------


def test_compress_empty_returns_empty_tuple() -> None:
    compressor = RuleBasedCompressor()
    result = compressor.compress([])
    assert result == ([], [])


# ---------------------------------------------------------------------------
# AC-2: relative order preserved
# ---------------------------------------------------------------------------


def test_compress_preserves_relative_order() -> None:
    chunks = [
        _chunk("c1", "def alpha(): pass", score=0.9),
        _chunk("c2", "def beta(): pass", score=0.8),
        _chunk("c3", "def gamma(): pass", score=0.7),
    ]
    compressor = RuleBasedCompressor()
    compressed, removed = compressor.compress(chunks)

    assert [c.chunk_id for c in compressed] == ["c1", "c2", "c3"]
    assert removed == []


# ---------------------------------------------------------------------------
# AC-3a: exact duplicates appear in removed with EXACT_DUPLICATE reason
# ---------------------------------------------------------------------------


def test_exact_duplicates_appear_in_removed() -> None:
    content = "def helper(): return 42\n"
    chunks = [
        _chunk("orig", content, score=0.9),
        _chunk("dup1", content, score=0.8),
        _chunk("dup2", content, score=0.7),
    ]
    compressor = RuleBasedCompressor()
    compressed, removed = compressor.compress(chunks)

    assert [c.chunk_id for c in compressed] == ["orig"]
    assert len(removed) == 2
    assert all(r.reason == RemovalReason.EXACT_DUPLICATE for r in removed)
    dup_ids = {r.chunk_id for r in removed}
    assert dup_ids == {"dup1", "dup2"}


# ---------------------------------------------------------------------------
# AC-3b: boilerplate chunks appear in removed with BOILERPLATE reason
# ---------------------------------------------------------------------------


def test_boilerplate_chunks_appear_in_removed() -> None:
    chunks = [
        _chunk("clean", "def foo(): pass\n", score=0.9),
        _chunk("boiler", _LICENSE_HEADER, score=0.8),
    ]
    compressor = RuleBasedCompressor()
    compressed, removed = compressor.compress(chunks)

    assert [c.chunk_id for c in compressed] == ["clean"]
    assert len(removed) == 1
    assert removed[0].chunk_id == "boiler"
    assert removed[0].reason == RemovalReason.BOILERPLATE


# ---------------------------------------------------------------------------
# AC-5: no chunk in both compressed output and removed list
# ---------------------------------------------------------------------------


def test_no_chunk_in_both_compressed_and_removed() -> None:
    content = "def dup(): pass\n"
    chunks = [
        _chunk("a", content, score=0.9),
        _chunk("b", content, score=0.8),
        _chunk("c", _LICENSE_HEADER, score=0.7),
        _chunk("d", "def unique(): pass\n", score=0.6),
    ]
    compressor = RuleBasedCompressor()
    compressed, removed = compressor.compress(chunks)

    compressed_ids = {c.chunk_id for c in compressed}
    removed_ids = {r.chunk_id for r in removed}
    assert compressed_ids.isdisjoint(removed_ids)


# ---------------------------------------------------------------------------
# Ordering: exact-dup removals before boilerplate removals
# ---------------------------------------------------------------------------


def test_removed_order_dedup_before_boilerplate() -> None:
    dup_content = "def dup(): pass\n"
    chunks = [
        _chunk("orig", dup_content, score=0.9),
        _chunk("dup", dup_content, score=0.85),  # exact duplicate
        _chunk("boiler", _LICENSE_HEADER, score=0.8),
    ]
    compressor = RuleBasedCompressor()
    _, removed = compressor.compress(chunks)

    assert removed[0].reason == RemovalReason.EXACT_DUPLICATE
    assert removed[1].reason == RemovalReason.BOILERPLATE


# ---------------------------------------------------------------------------
# Mixed: dedup + boilerplate on the same input
# ---------------------------------------------------------------------------


def test_mixed_dedup_and_boilerplate() -> None:
    dup_content = "def shared(): pass\n"
    chunks = [
        _chunk("k1", dup_content, score=0.9),
        _chunk("k2", "def unique_a(): pass\n", score=0.85),
        _chunk("k3", dup_content, score=0.8),    # exact dup of k1
        _chunk("k4", _LICENSE_HEADER, score=0.75),  # boilerplate
        _chunk("k5", "def unique_b(): pass\n", score=0.7),
    ]
    compressor = RuleBasedCompressor()
    compressed, removed = compressor.compress(chunks)

    compressed_ids = [c.chunk_id for c in compressed]
    removed_ids = [r.chunk_id for r in removed]

    assert "k1" in compressed_ids
    assert "k2" in compressed_ids
    assert "k5" in compressed_ids
    assert "k3" in removed_ids
    assert "k4" in removed_ids
    assert len(compressed_ids) == 3
    assert len(removed_ids) == 2


# ---------------------------------------------------------------------------
# Dependency injection: custom deduplicator and detector
# ---------------------------------------------------------------------------


def test_custom_deduplicator_injection() -> None:
    mock_dedup = MagicMock()
    chunk = _chunk("x", "content")
    mock_dedup.deduplicate.return_value = ([chunk], [])

    compressor = RuleBasedCompressor(deduplicator=mock_dedup)
    compressor.compress([chunk])

    mock_dedup.deduplicate.assert_called_once_with([chunk])


def test_custom_detector_injection() -> None:
    mock_detector = MagicMock()
    chunk = _chunk("x", "content")
    mock_detector.filter.return_value = ([chunk], [])

    compressor = RuleBasedCompressor(detector=mock_detector)
    compressor.compress([chunk])

    mock_detector.filter.assert_called_once()


# ---------------------------------------------------------------------------
# Single chunk passes through unchanged
# ---------------------------------------------------------------------------


def test_single_clean_chunk_passes_through() -> None:
    chunk = _chunk("solo", "def solo(): return 1\n")
    compressor = RuleBasedCompressor()
    compressed, removed = compressor.compress([chunk])

    assert compressed == [chunk]
    assert removed == []


# ---------------------------------------------------------------------------
# All chunks removed (all boilerplate)
# ---------------------------------------------------------------------------


def test_all_boilerplate_chunks_removed() -> None:
    chunks = [
        _chunk(f"b{i}", _LICENSE_HEADER, score=0.9 - i * 0.1)
        for i in range(3)
    ]
    compressor = RuleBasedCompressor()
    compressed, removed = compressor.compress(chunks)

    # First is kept by dedup (unique fingerprint), second and third are dups of first
    # But the first one is then filtered by boilerplate detector
    assert compressed == []
    assert len(removed) >= 1
