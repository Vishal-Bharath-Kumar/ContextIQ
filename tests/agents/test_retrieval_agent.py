"""Unit tests for ParallelConnectorDispatcher and retrieval_node.

TASK-US007-01 acceptance criteria:
  - all_succeed:            all active connectors return chunks; flat list assembled
  - one_fails:              one connector raises; others succeed; failed_sources recorded
  - all_fail:               every connector raises; chunks empty; all in failed_sources
  - empty_source_list:      no sources → empty FetchAllResult
  - inactive_connector:     source absent from registry (get() → None) is silently skipped
  - timeout_propagated:     asyncio.TimeoutError from _fetch_one captured as FailedSource
  - retrieval_node_returns: node returns correct state keys populated from FetchAllResult
  - registry_not_set:       retrieval_node raises RuntimeError when registry missing
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.agents.nodes.retrieval as retrieval_module
from src.agents.nodes.retrieval import (
    get_connector_registry,
    retrieval_node,
    set_connector_registry,
)
from src.agents.retrieval.parallel_dispatcher import (
    FailedSource,
    FetchAllResult,
    ParallelConnectorDispatcher,
)
from src.agents.schemas.execution_plan import ExecutionPlan, RankingStrategy
from src.agents.state import AgentState, ExecutionStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connector_result(
    source_id: str = "item-1",
    content: str = "hello world",
) -> ConnectorResult:
    return ConnectorResult(
        source_id=source_id,
        content=content,
        metadata=ResultMetadata(source_url="https://example.com", author="alice"),
        fetched_at=datetime(2026, 7, 16, tzinfo=UTC),
    )


def _make_mock_connector(results: list[ConnectorResult] | Exception) -> MagicMock:
    connector = MagicMock()
    if isinstance(results, Exception):
        connector.fetch = AsyncMock(side_effect=results)
    else:
        connector.fetch = AsyncMock(return_value=results)
    return connector


def _make_registry(source_map: dict[str, object | None]) -> MagicMock:
    """Build a fake ConnectorRegistry whose get() follows source_map."""
    registry = MagicMock()
    registry.get.side_effect = lambda src: source_map.get(src)
    return registry


def _make_state(**overrides: object) -> AgentState:
    base: AgentState = {
        "request_id": "req-test-001",
        "user_id": "user-test-001",
        "username": "tester",
        "roles": ["viewer"],
        "tool_name": "get_context",
        "prompt": "what is the auth flow?",
        "timestamp": "2026-07-16T00:00:00Z",
        "status": ExecutionStatus.PENDING,
        "current_node": "intent_agent",
        "error": None,
        "intent_type": "technical",
        "intent_confidence": 0.9,
        "execution_plan": ExecutionPlan(
            sources=["github"],
            token_budget_total=8000,
            token_budget_per_source={"github": 4000},
            ranking_strategy=RankingStrategy.SEMANTIC,
            cache_eligible=False,
        ),
        "raw_context": None,
        "ranked_context": None,
        "compressed_context": None,
        "tokens_before_compression": None,
        "tokens_after_compression": None,
        "governance_decisions": None,
        "redacted_chunks": None,
        "selected_model": None,
        "model_routing_score": None,
        "final_response": None,
    }
    return {**base, **overrides}  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# ParallelConnectorDispatcher tests
# ---------------------------------------------------------------------------


class TestParallelConnectorDispatcherAllSucceed:
    async def test_all_chunks_collected(self) -> None:
        result_a = _make_connector_result("doc-1", "content A")
        result_b = _make_connector_result("doc-2", "content B")
        registry = _make_registry(
            {
                "github": _make_mock_connector([result_a]),
                "confluence": _make_mock_connector([result_b]),
            }
        )
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="auth flow",
            source_ids=["github", "confluence"],
            token_budget_per_source={},
        )

        assert len(out.chunks) == 2
        assert out.failed_sources == []
        source_ids = {c.source_id for c in out.chunks}
        assert source_ids == {"github", "confluence"}

    async def test_chunk_fields_mapped_correctly(self) -> None:
        cr = _make_connector_result("doc-42", "some content")
        registry = _make_registry({"github": _make_mock_connector([cr])})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q", source_ids=["github"], token_budget_per_source={}
        )

        chunk = out.chunks[0]
        assert chunk.source_id == "github"
        assert chunk.chunk_id == "github:doc-42"
        assert chunk.content == "some content"
        assert chunk.token_count >= 1
        assert chunk.score == 0.0
        assert chunk.metadata["source_url"] == "https://example.com"

    async def test_single_gather_call(self) -> None:
        """fetch_all must delegate to asyncio.gather (single call)."""
        connector = _make_mock_connector([_make_connector_result()])
        registry = _make_registry({"src1": connector})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        with patch("asyncio.gather", wraps=asyncio.gather) as mock_gather:
            await dispatcher.fetch_all(
                query="q", source_ids=["src1"], token_budget_per_source={}
            )
            mock_gather.assert_called_once()
            _, kwargs = mock_gather.call_args
            assert kwargs.get("return_exceptions") is True


class TestParallelConnectorDispatcherOneFails:
    async def test_successful_chunks_still_returned(self) -> None:
        good = _make_mock_connector([_make_connector_result("ok", "good data")])
        bad = _make_mock_connector(RuntimeError("boom"))
        registry = _make_registry({"good_src": good, "bad_src": bad})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q",
            source_ids=["good_src", "bad_src"],
            token_budget_per_source={},
        )

        assert len(out.chunks) == 1
        assert out.chunks[0].source_id == "good_src"
        assert len(out.failed_sources) == 1

    async def test_failed_source_recorded_correctly(self) -> None:
        registry = _make_registry({"broken": _make_mock_connector(ValueError("oops"))})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q", source_ids=["broken"], token_budget_per_source={}
        )

        assert out.chunks == []
        assert len(out.failed_sources) == 1
        fs: FailedSource = out.failed_sources[0]
        assert fs.source_id == "broken"
        assert fs.error_type == "ValueError"
        assert fs.message == "oops"


class TestParallelConnectorDispatcherAllFail:
    async def test_empty_chunks_all_failures_recorded(self) -> None:
        registry = _make_registry(
            {
                "src1": _make_mock_connector(RuntimeError("err1")),
                "src2": _make_mock_connector(RuntimeError("err2")),
            }
        )
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q", source_ids=["src1", "src2"], token_budget_per_source={}
        )

        assert out.chunks == []
        assert len(out.failed_sources) == 2
        failed_ids = {fs.source_id for fs in out.failed_sources}
        assert failed_ids == {"src1", "src2"}


class TestParallelConnectorDispatcherEmptySourceList:
    async def test_returns_empty_result(self) -> None:
        registry = _make_registry({})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q", source_ids=[], token_budget_per_source={}
        )

        assert out == FetchAllResult(chunks=[], failed_sources=[])


class TestParallelConnectorDispatcherInactiveConnector:
    async def test_inactive_source_silently_skipped(self) -> None:
        """Sources whose registry.get() returns None must be skipped without error."""
        active = _make_mock_connector([_make_connector_result("x", "data")])
        registry = _make_registry({"active_src": active, "inactive_src": None})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q",
            source_ids=["active_src", "inactive_src"],
            token_budget_per_source={},
        )

        assert len(out.chunks) == 1
        assert out.failed_sources == []
        active.fetch.assert_called_once()

    async def test_unknown_source_silently_skipped(self) -> None:
        registry = _make_registry({})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        out = await dispatcher.fetch_all(
            query="q", source_ids=["nonexistent"], token_budget_per_source={}
        )

        assert out.chunks == []
        assert out.failed_sources == []


class TestParallelConnectorDispatcherTimeout:
    async def test_timeout_captured_as_failed_source(self) -> None:
        async def _slow(_q: ConnectorQuery) -> list[ConnectorResult]:
            await asyncio.sleep(60)
            return []  # pragma: no cover

        connector = MagicMock()
        connector.fetch = _slow
        registry = _make_registry({"slow_src": connector})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=0.01)

        out = await dispatcher.fetch_all(
            query="q", source_ids=["slow_src"], token_budget_per_source={}
        )

        assert out.chunks == []
        assert len(out.failed_sources) == 1
        assert out.failed_sources[0].source_id == "slow_src"
        assert out.failed_sources[0].error_type == "ConnectorTimeoutError"


class TestParallelConnectorDispatcherTokenBudget:
    async def test_token_budget_passed_as_filter(self) -> None:
        connector = _make_mock_connector([])
        registry = _make_registry({"src": connector})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        await dispatcher.fetch_all(
            query="q",
            source_ids=["src"],
            token_budget_per_source={"src": 512},
        )

        call_args = connector.fetch.call_args
        query_arg: ConnectorQuery = call_args[0][0]
        assert query_arg.filters.get("token_budget") == "512"

    async def test_no_token_budget_omits_filter(self) -> None:
        connector = _make_mock_connector([])
        registry = _make_registry({"src": connector})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        await dispatcher.fetch_all(
            query="q", source_ids=["src"], token_budget_per_source={}
        )

        call_args = connector.fetch.call_args
        query_arg: ConnectorQuery = call_args[0][0]
        assert "token_budget" not in query_arg.filters

    async def test_github_query_rewritten_for_code_related_intent(self) -> None:
        connector = _make_mock_connector([])
        registry = _make_registry({"github": connector})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        await dispatcher.fetch_all(
            query="Use the ContextIQ MCP generate_context tool to find real source code context related to FastAPI in this repository.",
            source_ids=["github"],
            token_budget_per_source={},
            intent_type="code-gen",
        )

        query_arg: ConnectorQuery = connector.fetch.call_args[0][0]
        assert "FastAPI" in query_arg.query
        assert "path:src" in query_arg.query

    async def test_github_query_rewritten_for_code_focused_prompt_even_if_non_code_intent(self) -> None:
        connector = _make_mock_connector([])
        registry = _make_registry({"github": connector})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        await dispatcher.fetch_all(
            query="Find real source code context related to FastAPI in this repository.",
            source_ids=["github"],
            token_budget_per_source={},
            intent_type="docs",
        )

        query_arg: ConnectorQuery = connector.fetch.call_args[0][0]
        assert "FastAPI" in query_arg.query
        assert "path:src" in query_arg.query

    async def test_github_query_rewrite_drops_low_signal_prompt_words(self) -> None:
        connector = _make_mock_connector([])
        registry = _make_registry({"github": connector})
        dispatcher = ParallelConnectorDispatcher(registry, timeout_seconds=5.0)

        await dispatcher.fetch_all(
            query=(
                "Explain why the local ContextIQ repo retrieval is now working after the GitHub source fix. "
                "Base the answer only on ContextIQ-retrieved evidence. Include concrete retrieved items "
                "from the ContextIQ GitHub source if available."
            ),
            source_ids=["github"],
            token_budget_per_source={},
            intent_type="debugging",
        )

        query_arg: ConnectorQuery = connector.fetch.call_args[0][0]
        assert "retrieval" in query_arg.query
        assert "source" in query_arg.query
        assert "path:src" in query_arg.query
        assert "evidence" not in query_arg.query.lower()
        assert "available" not in query_arg.query.lower()
        assert "contextiq" not in query_arg.query.lower()


# ---------------------------------------------------------------------------
# retrieval_node tests
# ---------------------------------------------------------------------------


class TestRetrievalNode:
    @pytest.fixture(autouse=True)
    def reset_registry(self) -> None:
        """Reset module-level registry singleton after each test."""
        original = retrieval_module._registry
        yield
        retrieval_module._registry = original

    async def test_node_returns_correct_keys(self) -> None:
        connector = _make_mock_connector([_make_connector_result("item-1", "content")])
        registry = _make_registry({"github": connector})
        set_connector_registry(registry)

        state = _make_state()

        result = await retrieval_node(state)

        assert result["current_node"] == "retrieval_agent"
        assert result["status"] == ExecutionStatus.RUNNING
        assert isinstance(result["raw_context"], list)
        assert isinstance(result["ranked_context"], list)

    async def test_node_raw_context_is_flat_chunk_list(self) -> None:
        r1 = _make_connector_result("d1", "alpha")
        r2 = _make_connector_result("d2", "beta")
        connector = _make_mock_connector([r1, r2])
        registry = _make_registry({"github": connector})
        set_connector_registry(registry)

        state = _make_state()
        result = await retrieval_node(state)

        assert len(result["raw_context"]) == 2
        assert result["raw_context"] == result["ranked_context"]

    async def test_node_with_no_execution_plan(self) -> None:
        registry = _make_registry({})
        set_connector_registry(registry)

        state = _make_state(execution_plan=None)
        with pytest.raises(AttributeError):
            await retrieval_node(state)

    async def test_registry_not_initialised_raises(self) -> None:
        retrieval_module._registry = None

        state = _make_state()
        with pytest.raises(RuntimeError, match="ConnectorRegistry has not been initialised"):
            await retrieval_node(state)

    async def test_set_and_get_registry_round_trip(self) -> None:
        registry = _make_registry({})
        set_connector_registry(registry)
        assert get_connector_registry() is registry

    async def test_code_related_intent_prefers_source_code_over_docs(self) -> None:
        code = ConnectorResult(
            source_id="code-1",
            content="def app(): return 'ok'",
            metadata=ResultMetadata(
                source_url="https://example.com/src/main.py",
                extra={"file_path": "src/main.py"},
            ),
            fetched_at=datetime(2026, 7, 16, tzinfo=UTC),
        )
        docs = ConnectorResult(
            source_id="doc-1",
            content="# README",
            metadata=ResultMetadata(
                source_url="https://example.com/docs/README.md",
                extra={"file_path": "docs/README.md"},
            ),
            fetched_at=datetime(2026, 7, 16, tzinfo=UTC),
        )
        connector = _make_mock_connector([docs, code])
        registry = _make_registry({"github": connector})
        set_connector_registry(registry)

        state = _make_state(intent_type="code-gen")
        result = await retrieval_node(state)

        assert result["raw_context"][0]["metadata"]["file_path"] == "docs/README.md"
        assert result["ranked_context"][0]["metadata"]["file_path"] == "src/main.py"
