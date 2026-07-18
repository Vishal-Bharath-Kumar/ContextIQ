"""Shared test fixtures for the semantic deduplication test suite."""

from __future__ import annotations

from datetime import UTC, datetime

from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

_TS = datetime(2024, 1, 1, tzinfo=UTC)


def _meta(file_path: str = "a/b.txt") -> ChunkMetadata:
    return ChunkMetadata(file_path=file_path, timestamp=_TS, author="tester")


def make_chunk(
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
        metadata=_meta(),
    )


def make_chunks(n: int, source_id: str = "github") -> list[RetrievedChunk]:
    """Return n distinct chunks with unique chunk_ids and varied scores."""
    return [
        make_chunk(
            chunk_id=f"chunk_{i:04d}",
            content=f"This is test chunk number {i} with some content to embed.",
            source_id=source_id,
            score=round(0.5 + (i % 50) * 0.01, 4),
        )
        for i in range(n)
    ]
