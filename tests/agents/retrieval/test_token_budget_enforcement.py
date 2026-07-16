"""Unit tests for per-source token budget enforcement.

TASK-US010-04 acceptance criteria:
  - truncate_basic:           keeps only complete chunks fitting within budget
  - truncate_exact_boundary:  chunk fitting exactly at budget is kept
  - truncate_zero_budget:     zero budget → empty list
  - truncate_single_exceeds:  single chunk exceeding budget → empty list
  - truncate_empty_input:     empty chunk list → empty list
  - dispatcher_budget_applied: _fetch_one truncates ContextChunks to token_budget
  - dispatcher_no_budget:     _fetch_one with token_budget=None returns all chunks
  - retrieval_node_typed_plan: retrieval_node reads typed ExecutionPlan without KeyError
  - source_filtering:         only sources in plan.sources are dispatched
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.retrieval.token_truncator import truncate_to_budget

# ---------------------------------------------------------------------------
# truncate_to_budget tests
# ---------------------------------------------------------------------------


class TestTruncateToBudget:
    def test_keeps_chunks_within_budget(self) -> None:
        # "hello" ≈ 1 token, "world" ≈ 1 token — a budget of 2 keeps both
        result = truncate_to_budget(["hello", "world"], token_budget=100)
        assert result == ["hello", "world"]

    def test_stops_before_exceeding_budget(self) -> None:
        # Generate chunks with known token counts; token_budget=1 keeps first only
        chunks = ["hello", "world"]
        result = truncate_to_budget(chunks, token_budget=1)
        # "hello" is 1 token in cl100k_base; "world" cannot fit
        assert result == ["hello"]

    def test_exact_budget_boundary_keeps_chunk(self) -> None:
        # A chunk whose token count equals the remaining budget must be kept
        chunk = "hello"  # 1 token
        result = truncate_to_budget([chunk], token_budget=1)
        assert result == ["hello"]

    def test_zero_budget_returns_empty(self) -> None:
        result = truncate_to_budget(["anything"], token_budget=0)
        assert result == []

    def test_single_chunk_exceeds_budget_returns_empty(self) -> None:
        # "hello world" is 2 tokens; budget of 1 cannot fit it
        result = truncate_to_budget(["hello world"], token_budget=1)
        assert result == []

    def test_empty_input_returns_empty(self) -> None:
        result = truncate_to_budget([], token_budget=100)
        assert result == []

    def test_multi_chunk_partial_fit(self) -> None:
        # "alpha" ≈ 1 token, "beta" ≈ 1 token, "gamma" ≈ 1 token
        # budget=2 → first two fit, third is excluded
        result = truncate_to_budget(["alpha", "beta", "gamma"], token_budget=2)
        assert result == ["alpha", "beta"]

    def test_returns_only_complete_chunks(self) -> None:
        # Verify no partial chunk ever leaks through
        chunks = ["one token"] * 10
        result = truncate_to_budget(chunks, token_budget=5)
        # Each "one token" is 2 tokens in cl100k_base ("one", "token")
        # 5 // 2 = 2 chunks fit (4 tokens used); the 3rd would exceed budget
        assert all(c == "one token" for c in result)
        # All returned chunks are complete (same string as input chunks)
        for chunk in result:
            assert chunk in chunks


# ---------------------------------------------------------------------------
# ParallelConnectorDispatcher budget integration tests
# ---------------------------------------------------------------------------


def _make_result_metadata() -> object:
    from src.connector_sdk.schemas.result import ResultMetadata

    return ResultMetadata(source_url="https://example.com", author="bot")


def _make_connector_result(source_id: str = "item-1", content: str = "hello") -> object:
    from src.connector_sdk.schemas.result import ConnectorResult

    return ConnectorResult(
        source_id=source_id,
        content=content,
        metadata=_make_result_metadata(),
        fetched_at=datetime(2026, 7, 16, tzinfo=UTC),
    )


def _make_registry(source_map: dict) -> MagicMock:
    registry = MagicMock()
    registry.get.side_effect = lambda src: source_map.get(src)
    return registry


class TestDispatcherBudgetEnforcement:
    async def test_token_budget_truncates_chunks(self) -> None:
        """Chunks exceeding the token budget for a source are dropped."""
        # Three single-token words; budget of 2 allows only the first two
        results = [
            _make_connector_result(f"doc-{i}", word)
            for i, word in enumerate(["alpha", "beta", "gamma"])
        ]
        connector = MagicMock()
        connector.fetch = AsyncMock(return_value=results)
        connector.source_id = "src1"

        registry = _make_registry({"src1": connector})
        from src.agents.retrieval.parallel_dispatcher import ParallelConnectorDispatcher

        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q",
            source_ids=["src1"],
            token_budget_per_source={"src1": 2},
        )

        # alpha=1 token, beta=1 token → 2 fit; gamma cannot fit
        assert len(out.chunks) == 2
        contents = [c.content for c in out.chunks]
        assert contents == ["alpha", "beta"]

    async def test_no_budget_returns_all_chunks(self) -> None:
        """When token_budget is absent for a source, all chunks are returned."""
        results = [
            _make_connector_result(f"doc-{i}", word)
            for i, word in enumerate(["alpha", "beta", "gamma"])
        ]
        connector = MagicMock()
        connector.fetch = AsyncMock(return_value=results)
        connector.source_id = "src1"

        registry = _make_registry({"src1": connector})
        from src.agents.retrieval.parallel_dispatcher import ParallelConnectorDispatcher

        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q",
            source_ids=["src1"],
            token_budget_per_source={},  # no budget for src1
        )

        assert len(out.chunks) == 3

    async def test_zero_budget_returns_empty_for_source(self) -> None:
        """A zero token budget results in no chunks from that source."""
        results = [_make_connector_result("doc-1", "hello")]
        connector = MagicMock()
        connector.fetch = AsyncMock(return_value=results)
        connector.source_id = "src1"

        registry = _make_registry({"src1": connector})
        from src.agents.retrieval.parallel_dispatcher import ParallelConnectorDispatcher

        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q",
            source_ids=["src1"],
            token_budget_per_source={"src1": 0},
        )

        assert out.chunks == []
        assert out.failed_sources == []

    async def test_budget_applied_per_source_independently(self) -> None:
        """Budget truncation is applied independently to each connector."""
        results_a = [
            _make_connector_result(f"a-{i}", word)
            for i, word in enumerate(["alpha", "beta", "gamma"])
        ]
        results_b = [
            _make_connector_result(f"b-{i}", word)
            for i, word in enumerate(["one", "two"])
        ]
        conn_a = MagicMock()
        conn_a.fetch = AsyncMock(return_value=results_a)
        conn_a.source_id = "src_a"
        conn_b = MagicMock()
        conn_b.fetch = AsyncMock(return_value=results_b)
        conn_b.source_id = "src_b"

        registry = _make_registry({"src_a": conn_a, "src_b": conn_b})
        from src.agents.retrieval.parallel_dispatcher import ParallelConnectorDispatcher

        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q",
            source_ids=["src_a", "src_b"],
            token_budget_per_source={"src_a": 1, "src_b": 100},
        )

        src_a_chunks = [c for c in out.chunks if c.source_id == "src_a"]
        src_b_chunks = [c for c in out.chunks if c.source_id == "src_b"]
        assert len(src_a_chunks) == 1  # budget=1 → only "alpha" fits
        assert len(src_b_chunks) == 2  # budget=100 → both fit


# ---------------------------------------------------------------------------
# Source filtering test
# ---------------------------------------------------------------------------


class TestSourceFiltering:
    async def test_connectors_not_in_plan_never_called(self) -> None:
        """Connectors absent from source_ids are never dispatched."""
        registered_connector = MagicMock()
        registered_connector.fetch = AsyncMock(
            return_value=[_make_connector_result("doc-1", "data")]
        )
        registered_connector.source_id = "allowed"

        excluded_connector = MagicMock()
        excluded_connector.fetch = AsyncMock(
            return_value=[_make_connector_result("doc-2", "secret")]
        )
        excluded_connector.source_id = "excluded"

        registry = _make_registry(
            {"allowed": registered_connector, "excluded": excluded_connector}
        )
        from src.agents.retrieval.parallel_dispatcher import ParallelConnectorDispatcher

        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q",
            source_ids=["allowed"],  # "excluded" is not listed
            token_budget_per_source={},
        )

        excluded_connector.fetch.assert_not_called()
        assert all(c.source_id == "allowed" for c in out.chunks)


# ---------------------------------------------------------------------------
# retrieval_node typed ExecutionPlan test
# ---------------------------------------------------------------------------


class TestRetrievalNodeTypedPlan:
    async def test_typed_execution_plan_no_keyerror(self) -> None:
        """retrieval_node must access typed ExecutionPlan without raising KeyError."""
        from src.agents.nodes.retrieval import retrieval_node, set_connector_registry
        from src.agents.retrieval.parallel_dispatcher import FetchAllResult
        from src.agents.schemas.execution_plan import ExecutionPlan, RankingStrategy
        from src.agents.state import AgentState, ExecutionStatus

        plan = ExecutionPlan(
            sources=["github"],
            token_budget_total=8000,
            token_budget_per_source={"github": 2000},
            ranking_strategy=RankingStrategy.SEMANTIC,
            cache_eligible=False,
        )

        state: AgentState = {
            "request_id": "req-001",
            "user_id": "user-001",
            "username": "tester",
            "roles": ["viewer"],
            "tool_name": "get_context",
            "prompt": "what is the auth flow?",
            "timestamp": "2026-07-16T00:00:00Z",
            "status": ExecutionStatus.PENDING,
            "current_node": "intent_agent",
            "error": None,
            "intent_type": None,
            "intent_confidence": None,
            "intent_source_list": None,
            "execution_plan": plan,
            "requires_clarification": None,
            "raw_context": None,
            "ranked_context": None,
            "degraded_sources": None,
            "compressed_context": None,
            "tokens_before_compression": None,
            "tokens_after_compression": None,
            "governance_decisions": None,
            "redacted_chunks": None,
            "selected_model": None,
            "model_routing_score": None,
            "final_response": None,
        }

        mock_registry = _make_registry({"github": None})  # github not registered → skip
        set_connector_registry(mock_registry)

        # Should not raise KeyError or AttributeError
        result = await retrieval_node(state)

        assert result["current_node"] == "retrieval_agent"
        assert result["status"] == ExecutionStatus.RUNNING
        assert result["raw_context"] is not None
        assert result["ranked_context"] is not None
