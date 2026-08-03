"""CI benchmark: SemanticDeduplicator must process 50 chunks in < 300 ms (TASK-US016-04)."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from src.compression.semantic.semantic_deduplicator import SemanticDeduplicator
from tests.compression.semantic.fixtures import make_chunks

CHUNK_COUNT = 50
EMBED_DIM   = 384


def _mock_embeddings(n: int) -> np.ndarray:
    """Produce n/5 clusters of 5 near-identical vectors to guarantee ≥ 15% reduction."""
    rng = np.random.default_rng(42)
    base = rng.standard_normal((n // 5, EMBED_DIM)).astype(np.float32)
    # Tile each base vector 5 times with tiny noise → cosine similarity > 0.99
    tiles = np.repeat(base, 5, axis=0)
    tiles += rng.standard_normal(tiles.shape).astype(np.float32) * 0.001
    return tiles[:n]


@pytest.mark.benchmark(max_time=0.3)
def test_semantic_dedup_300ms_benchmark(benchmark: pytest.FixtureRequest) -> None:
    mock_embedder = MagicMock()
    mock_embedder.embed_batch.return_value = _mock_embeddings(CHUNK_COUNT)

    chunks = make_chunks(CHUNK_COUNT)
    deduplicator = SemanticDeduplicator(embedder=mock_embedder)

    kept, removed, _ = benchmark(lambda: deduplicator.deduplicate(chunks))
    assert len(kept) < CHUNK_COUNT           # at least one cluster was merged
    assert len(removed) >= CHUNK_COUNT // 5 * 4  # 4 of 5 per cluster removed
