"""Benchmark and token-reduction tests for RuleBasedCompressor (TASK-US015-04)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.compression.rule_based_compressor import RuleBasedCompressor
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

LICENSE_HEADER = "// SPDX-License-Identifier: MIT\n// Copyright (c) 2024 ACME Corp\n"


def _make_chunks(n: int) -> list[RetrievedChunk]:
    now = datetime.now(UTC)
    return [
        RetrievedChunk(
            chunk_id=f"chunk-{i:03d}",
            source_id="github",
            content=(LICENSE_HEADER if i % 5 == 0 else f"def function_{i}(): pass\n"),
            score=0.9 - i * 0.01,
            search_mode="rrf",
            metadata=ChunkMetadata(file_path=f"src/mod_{i}.py", timestamp=now, author="dev"),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 100 ms CI benchmark — AC-6
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(max_time=0.1)
def test_rule_based_compressor_100ms_benchmark(benchmark: object) -> None:
    compressor = RuleBasedCompressor()
    chunks = _make_chunks(50)

    compressed, removed = benchmark(lambda: compressor.compress(chunks))

    assert len(removed) >= 10  # 10 license-header chunks + possible duplicates
    assert all(c.score >= 0.0 for c in compressed)


# ---------------------------------------------------------------------------
# Token reduction ≥ 10% — AC-7
# ---------------------------------------------------------------------------


def test_token_reduction_at_least_10_percent() -> None:
    from src.retrieval.ranking.filters import count_tokens

    compressor = RuleBasedCompressor()
    chunks = _make_chunks(50)
    compressed, _ = compressor.compress(chunks)

    original_tokens = sum(count_tokens(c.content) for c in chunks)
    compressed_tokens = sum(count_tokens(c.content) for c in compressed)
    reduction = (original_tokens - compressed_tokens) / original_tokens
    assert reduction >= 0.10, f"Token reduction {reduction:.1%} < 10%"
