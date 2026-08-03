"""Unit tests for ContextAggregator.

TASK-US007-03 acceptance criteria:
  - all_succeed:               all connectors return chunks; flat list assembled
  - partial_failure:           some connectors fail; successful chunks aggregated;
                               degraded_sources populated for failures
  - all_fail:                  all connectors fail; empty chunks; degraded_sources populated
  - per_source_budget:         chunks truncated when a source exceeds its token budget
  - global_budget:             global token cap applied across all sources
  - duplicate_chunk_ids:       duplicate chunk_id appears only once in output
  - source_order_preserved:    chunks maintain first-seen source insertion order
  - integration_2_succeed_1_timeout: two sources succeed, one fails; degraded_sources has 1 entry
"""
from __future__ import annotations

import pytest

from src.agents.retrieval.aggregator import AggregatedContext, ContextAggregator, DegradedSource
from src.agents.retrieval.parallel_dispatcher import (
    ContextChunk,
    FailedSource,
    FetchAllResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunk(chunk_id: str, source_id: str, token_count: int, content: str = "x") -> ContextChunk:
    return ContextChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        content=content,
        token_count=token_count,
    )


def _failed(source_id: str, error_type: str = "RuntimeError", message: str = "err") -> FailedSource:
    return FailedSource(source_id=source_id, error_type=error_type, message=message)


def _fetch_result(
    chunks: list[ContextChunk] | None = None,
    failed_sources: list[FailedSource] | None = None,
) -> FetchAllResult:
    return FetchAllResult(
        chunks=chunks or [],
        failed_sources=failed_sources or [],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAllSucceed:
    def test_flat_list_assembled(self) -> None:
        chunks = [
            _chunk("c1", "src-a", 100),
            _chunk("c2", "src-b", 200),
            _chunk("c3", "src-a", 50),
        ]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=chunks),
            token_budget_per_source={},
            global_token_budget=10_000,
        )

        assert len(result.chunks) == 3
        assert result.total_token_count == 350
        assert result.source_count == 2
        assert result.degraded_sources == []

    def test_returns_aggregated_context_type(self) -> None:
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=[_chunk("c1", "src-a", 100)]),
            token_budget_per_source={},
            global_token_budget=10_000,
        )
        assert isinstance(result, AggregatedContext)


class TestPartialFailure:
    def test_successful_chunks_present_failed_sources_recorded(self) -> None:
        chunks = [_chunk("c1", "src-a", 100), _chunk("c2", "src-b", 200)]
        failed = [_failed("src-c", error_type="ConnectorTimeoutError", message="timed out after 5s")]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=chunks, failed_sources=failed),
            token_budget_per_source={},
            global_token_budget=10_000,
        )

        assert len(result.chunks) == 2
        assert len(result.degraded_sources) == 1
        ds = result.degraded_sources[0]
        assert ds.source_id == "src-c"
        assert ds.error_type == "ConnectorTimeoutError"
        assert ds.message == "timed out after 5s"

    def test_degraded_source_schema(self) -> None:
        failed = [_failed("src-x", "ValueError", "bad value")]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(failed_sources=failed),
            token_budget_per_source={},
            global_token_budget=10_000,
        )
        assert isinstance(result.degraded_sources[0], DegradedSource)


class TestAllFail:
    def test_empty_chunks_all_in_degraded_sources(self) -> None:
        failed = [_failed("src-a"), _failed("src-b"), _failed("src-c")]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(failed_sources=failed),
            token_budget_per_source={},
            global_token_budget=10_000,
        )

        assert result.chunks == []
        assert result.total_token_count == 0
        assert result.source_count == 0
        assert len(result.degraded_sources) == 3

    def test_source_ids_match(self) -> None:
        failed = [_failed("src-a"), _failed("src-b")]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(failed_sources=failed),
            token_budget_per_source={},
            global_token_budget=10_000,
        )
        ids = {ds.source_id for ds in result.degraded_sources}
        assert ids == {"src-a", "src-b"}


class TestPerSourceBudget:
    def test_chunks_truncated_at_source_budget(self) -> None:
        # src-a has a budget of 150; c1=100 fits, c2=100 would exceed (100+100=200>150) → truncated
        chunks = [
            _chunk("c1", "src-a", 100),
            _chunk("c2", "src-a", 100),
            _chunk("c3", "src-a", 10),
        ]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=chunks),
            token_budget_per_source={"src-a": 150},
            global_token_budget=10_000,
        )

        source_a_chunks = [c for c in result.chunks if c.source_id == "src-a"]
        assert len(source_a_chunks) == 1
        assert source_a_chunks[0].chunk_id == "c1"

    def test_multiple_sources_independent_budgets(self) -> None:
        chunks = [
            _chunk("a1", "src-a", 100),
            _chunk("a2", "src-a", 100),
            _chunk("b1", "src-b", 100),
            _chunk("b2", "src-b", 100),
        ]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=chunks),
            token_budget_per_source={"src-a": 150, "src-b": 250},
            global_token_budget=10_000,
        )

        src_a = [c for c in result.chunks if c.source_id == "src-a"]
        src_b = [c for c in result.chunks if c.source_id == "src-b"]
        # src-a: a1 fits (100), a2 exceeds (100+100=200>150)
        assert len(src_a) == 1
        # src-b: b1 fits (100), b2 fits (100+100=200 ≤ 250)
        assert len(src_b) == 2

    def test_source_without_explicit_budget_uses_global(self) -> None:
        chunks = [_chunk("c1", "src-x", 300), _chunk("c2", "src-x", 300)]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=chunks),
            token_budget_per_source={},
            global_token_budget=500,
        )
        src_x = [c for c in result.chunks if c.source_id == "src-x"]
        # global_token_budget=500 used as source budget; c1=300 fits, c1+c2=600>500 → c2 excluded
        assert len(src_x) == 1


class TestGlobalBudget:
    def test_global_cap_enforced_across_sources(self) -> None:
        chunks = [
            _chunk("c1", "src-a", 300),
            _chunk("c2", "src-b", 300),
            _chunk("c3", "src-c", 300),
        ]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=chunks),
            token_budget_per_source={},
            global_token_budget=500,
        )

        # c1=300 fits; c1+c2=600>500 → c2, c3 excluded
        assert result.total_token_count == 300
        assert len(result.chunks) == 1
        assert result.chunks[0].chunk_id == "c1"

    def test_global_cap_zero_returns_empty(self) -> None:
        chunks = [_chunk("c1", "src-a", 100)]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=chunks),
            token_budget_per_source={},
            global_token_budget=0,
        )
        assert result.chunks == []
        assert result.total_token_count == 0


class TestDuplicateChunkIds:
    def test_duplicate_chunk_id_appears_once(self) -> None:
        chunks = [
            _chunk("dup-1", "src-a", 100),
            _chunk("dup-1", "src-a", 100),  # exact duplicate
            _chunk("unique", "src-a", 50),
        ]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=chunks),
            token_budget_per_source={},
            global_token_budget=10_000,
        )

        ids = [c.chunk_id for c in result.chunks]
        assert ids.count("dup-1") == 1
        assert len(result.chunks) == 2

    def test_same_chunk_id_different_sources_deduped(self) -> None:
        # Same chunk_id from two different sources → only first occurrence kept
        chunks = [
            _chunk("shared", "src-a", 100),
            _chunk("shared", "src-b", 100),
        ]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=chunks),
            token_budget_per_source={},
            global_token_budget=10_000,
        )
        assert len([c for c in result.chunks if c.chunk_id == "shared"]) == 1


class TestSourceOrderPreserved:
    def test_insertion_order_maintained(self) -> None:
        chunks = [
            _chunk("b1", "src-b", 50),
            _chunk("a1", "src-a", 50),
            _chunk("c1", "src-c", 50),
        ]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=chunks),
            token_budget_per_source={},
            global_token_budget=10_000,
        )
        source_order = [c.source_id for c in result.chunks]
        assert source_order == ["src-b", "src-a", "src-c"]


class TestIntegration2SucceedOneFail:
    def test_two_succeed_one_timeout(self) -> None:
        chunks = [
            _chunk("a1", "src-a", 200),
            _chunk("a2", "src-a", 150),
            _chunk("b1", "src-b", 300),
        ]
        failed = [
            _failed("src-c", error_type="ConnectorTimeoutError", message="timed out after 5.0s")
        ]
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(chunks=chunks, failed_sources=failed),
            token_budget_per_source={},
            global_token_budget=10_000,
        )

        # All 3 chunks from src-a and src-b present
        assert len(result.chunks) == 3
        source_ids = {c.source_id for c in result.chunks}
        assert source_ids == {"src-a", "src-b"}

        # Exactly one degraded source
        assert len(result.degraded_sources) == 1
        assert result.degraded_sources[0].source_id == "src-c"
        assert result.degraded_sources[0].error_type == "ConnectorTimeoutError"

    def test_empty_fetch_result_is_valid(self) -> None:
        result = ContextAggregator().aggregate(
            fetch_result=_fetch_result(),
            token_budget_per_source={},
            global_token_budget=8_000,
        )
        assert isinstance(result, AggregatedContext)
        assert result.chunks == []
        assert result.degraded_sources == []
        assert result.total_token_count == 0
        assert result.source_count == 0
