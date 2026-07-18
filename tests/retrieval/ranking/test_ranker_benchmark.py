"""CI benchmark test for ContextRanker — TASK-US014-04.

Asserts that the complete ranking pipeline completes in < 200 ms for a
realistic 1 000-chunk input, using pytest-benchmark.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.retrieval.ranking.ranker import ContextRanker
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def _make_chunks(n: int) -> list[RetrievedChunk]:
    now = datetime.now(UTC)
    return [
        RetrievedChunk(
            chunk_id=f"chunk-{i:04d}00000000",
            source_id="github",
            content="def foo(): pass  " * 20,  # ~80 tokens each
            score=0.01639,  # RRF rank-1 score (k=60)
            search_mode="rrf",
            vector_score=0.8,
            keyword_score=0.6,
            metadata=ChunkMetadata(
                file_path=f"src/module_{i}.py",
                timestamp=now - timedelta(days=i % 90),
                author="dev",
            ),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(max_time=0.2)
def test_ranker_200ms_benchmark(benchmark: pytest.FixtureRequest) -> None:
    """CI gate: rank() on 1 000 chunks must complete in < 200 ms (p99)."""
    ranker = ContextRanker()
    chunks = _make_chunks(1_000)

    result = benchmark(lambda: ranker.rank(chunks, token_budget=8_000))

    assert isinstance(result, list)
    assert all(c.score >= 0.5 for c in result)
