"""Tests for knowledge_graph_node — TASK-US029-04.

Covers all acceptance criteria:
  AC-1  Appends GraphContextItem dicts to ranked_context with source='knowledge_graph'.
  AC-2  graph_context_items matches GraphTraversalResult.items.
  AC-3  graph_traversal_skipped=True when remaining_tokens=0 (zero budget).
  AC-4  graph_traversal_skipped=True when EntityLinker.resolve() returns [].
  AC-5  graph_traversal_skipped=True when GraphTraversalClient.traverse() raises TimeoutError.
  AC-6  OTel span 'knowledge_graph.traverse' is created for every invocation.
  AC-7  graph_tokens_used equals GraphTraversalResult.total_tokens on the happy path.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.knowledge_graph.traversal.schemas import GraphContextItem, GraphTraversalResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ITEM = GraphContextItem(
    entity_id="entity-001",
    entity_type="Service",
    name="auth-service",
    hops=1,
    path_summary="auth-service -[DEPENDS_ON]-> user-repo",
    properties={"language": "Python"},
    token_count=42,
    source="knowledge_graph",
)

_TRAVERSAL_RESULT = GraphTraversalResult(
    items=[_ITEM],
    total_tokens=42,
    query_duration_ms=12.5,
    seeds_used=["entity-001"],
    truncated=False,
)

_RANKED_CONTEXT = [{"chunk_id": "c1", "text": "auth-service handles OAuth", "score": 0.9}]


def _base_state(**overrides: object) -> dict:
    base: dict = {
        "request_id": "req-001",
        "user_id": "user-001",
        "username": "alice",
        "roles": ["viewer"],
        "tool_name": "search",
        "prompt": "What does auth-service depend on?",
        "timestamp": "2026-07-17T00:00:00Z",
        "status": "running",
        "current_node": "knowledge_graph",
        "error": None,
        "intent_type": None,
        "intent_confidence": None,
        "intent_source_list": None,
        "execution_plan": {"remaining_tokens": 4000},
        "requires_clarification": None,
        "clarification_question": None,
        "clarification_round": 0,
        "raw_context": None,
        "ranked_context": list(_RANKED_CONTEXT),
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
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tracer_span() -> tuple[MagicMock, MagicMock]:
    """Mock OTel tracer so tests do not require a real OTLP backend."""
    mock_span = MagicMock()
    mock_span.__enter__ = MagicMock(return_value=mock_span)
    mock_span.__exit__ = MagicMock(return_value=False)
    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value = mock_span
    with patch(
        "src.knowledge_graph.nodes.knowledge_graph_node.tracer",
        mock_tracer,
    ):
        yield mock_tracer, mock_span


@pytest.fixture
def mock_langfuse() -> MagicMock:
    """Mock Langfuse client to avoid real HTTP calls."""
    mock_lf = MagicMock()
    with patch(
        "src.knowledge_graph.nodes.knowledge_graph_node.langfuse",
        mock_lf,
    ):
        yield mock_lf


@pytest.fixture
def mock_traversal_client() -> MagicMock:
    """Mock GraphTraversalClient.traverse()."""
    client = MagicMock()
    client.traverse = AsyncMock(return_value=_TRAVERSAL_RESULT)
    return client


@pytest.fixture
def mock_entity_linker(mock_traversal_client: MagicMock) -> MagicMock:
    """Mock EntityLinker.resolve() returning one seed."""
    linker = MagicMock()
    linker.resolve = AsyncMock(return_value=["entity-001"])
    return linker


# ---------------------------------------------------------------------------
# Tests — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_appends_to_ranked_context(
    mock_tracer_span: tuple,
    mock_langfuse: MagicMock,
    mock_traversal_client: MagicMock,
    mock_entity_linker: MagicMock,
) -> None:
    """AC-1: GraphContextItem dicts appended to ranked_context with source='knowledge_graph'."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    state = _base_state()

    with (
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
            return_value=mock_traversal_client,
        ),
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker",
            return_value=mock_entity_linker,
        ),
    ):
        result = await knowledge_graph_node(state)

    assert result["ranked_context"] is not None
    # Original item is preserved
    assert result["ranked_context"][0] == _RANKED_CONTEXT[0]
    # Graph item appended
    appended = result["ranked_context"][1]
    assert appended["source"] == "knowledge_graph"
    assert appended["entity_id"] == "entity-001"


@pytest.mark.asyncio
async def test_happy_path_graph_context_items_match_result(
    mock_tracer_span: tuple,
    mock_langfuse: MagicMock,
    mock_traversal_client: MagicMock,
    mock_entity_linker: MagicMock,
) -> None:
    """AC-2: graph_context_items matches GraphTraversalResult.items."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    state = _base_state()

    with (
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
            return_value=mock_traversal_client,
        ),
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker",
            return_value=mock_entity_linker,
        ),
    ):
        result = await knowledge_graph_node(state)

    assert result["graph_context_items"] == _TRAVERSAL_RESULT.items
    assert result["graph_traversal_skipped"] is False


@pytest.mark.asyncio
async def test_happy_path_graph_tokens_used(
    mock_tracer_span: tuple,
    mock_langfuse: MagicMock,
    mock_traversal_client: MagicMock,
    mock_entity_linker: MagicMock,
) -> None:
    """AC-7: graph_tokens_used equals GraphTraversalResult.total_tokens."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    state = _base_state()

    with (
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
            return_value=mock_traversal_client,
        ),
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker",
            return_value=mock_entity_linker,
        ),
    ):
        result = await knowledge_graph_node(state)

    assert result["graph_tokens_used"] == _TRAVERSAL_RESULT.total_tokens


# ---------------------------------------------------------------------------
# Tests — graceful skip conditions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skip_zero_token_budget(mock_tracer_span: tuple, mock_langfuse: MagicMock) -> None:
    """AC-3: graph_traversal_skipped=True when remaining_tokens=0."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    state = _base_state(execution_plan={"remaining_tokens": 0})

    result = await knowledge_graph_node(state)

    assert result["graph_traversal_skipped"] is True
    assert result["graph_tokens_used"] == 0
    assert result["graph_context_items"] == []
    # Original ranked_context must be unchanged
    assert result["ranked_context"] == _RANKED_CONTEXT


@pytest.mark.asyncio
async def test_skip_no_seed_entities(
    mock_tracer_span: tuple,
    mock_langfuse: MagicMock,
    mock_traversal_client: MagicMock,
) -> None:
    """AC-4: graph_traversal_skipped=True when EntityLinker.resolve() returns []."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    empty_linker = MagicMock()
    empty_linker.resolve = AsyncMock(return_value=[])

    state = _base_state()

    with (
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
            return_value=mock_traversal_client,
        ),
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker",
            return_value=empty_linker,
        ),
    ):
        result = await knowledge_graph_node(state)

    assert result["graph_traversal_skipped"] is True
    assert result["graph_tokens_used"] == 0
    assert result["graph_context_items"] == []
    assert result["ranked_context"] == _RANKED_CONTEXT


@pytest.mark.asyncio
async def test_skip_on_timeout(
    mock_tracer_span: tuple,
    mock_langfuse: MagicMock,
    mock_entity_linker: MagicMock,
) -> None:
    """AC-5: graph_traversal_skipped=True when traverse() raises asyncio.TimeoutError."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    timeout_client = MagicMock()
    timeout_client.traverse = AsyncMock(side_effect=asyncio.TimeoutError)

    state = _base_state()

    with (
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
            return_value=timeout_client,
        ),
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker",
            return_value=mock_entity_linker,
        ),
    ):
        result = await knowledge_graph_node(state)

    assert result["graph_traversal_skipped"] is True
    assert result["graph_tokens_used"] == 0
    assert result["graph_context_items"] == []
    assert result["ranked_context"] == _RANKED_CONTEXT


# ---------------------------------------------------------------------------
# Tests — OTel span always created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otel_span_created_on_skip(
    mock_langfuse: MagicMock,
) -> None:
    """AC-6: OTel span 'knowledge_graph.traverse' is created even when skipped."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    mock_span = MagicMock()
    mock_span.__enter__ = MagicMock(return_value=mock_span)
    mock_span.__exit__ = MagicMock(return_value=False)
    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value = mock_span

    state = _base_state(execution_plan={"remaining_tokens": 0})

    with patch(
        "src.knowledge_graph.nodes.knowledge_graph_node.tracer",
        mock_tracer,
    ):
        await knowledge_graph_node(state)

    mock_tracer.start_as_current_span.assert_called_once_with("knowledge_graph.traverse")


@pytest.mark.asyncio
async def test_otel_span_created_on_happy_path(
    mock_langfuse: MagicMock,
    mock_traversal_client: MagicMock,
    mock_entity_linker: MagicMock,
) -> None:
    """AC-6: OTel span 'knowledge_graph.traverse' created on the happy path."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    mock_span = MagicMock()
    mock_span.__enter__ = MagicMock(return_value=mock_span)
    mock_span.__exit__ = MagicMock(return_value=False)
    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value = mock_span

    state = _base_state()

    with (
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.tracer",
            mock_tracer,
        ),
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
            return_value=mock_traversal_client,
        ),
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker",
            return_value=mock_entity_linker,
        ),
    ):
        await knowledge_graph_node(state)

    mock_tracer.start_as_current_span.assert_called_once_with("knowledge_graph.traverse")


# ---------------------------------------------------------------------------
# TASK-US029-05 — AC-1 through AC-6 named tests
# ---------------------------------------------------------------------------

_US029_SEED_ID = "a3f1c2b4d5e6f708"


@pytest.mark.asyncio
async def test_node_triggers_traversal_with_seeds_from_ranked_context(
    ranked_context_with_entity_ids: list,
    mock_traversal_result,
) -> None:
    """AC-1: Cypher traversal is triggered using seeds extracted from ranked_context."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    mock_client = AsyncMock()
    mock_client.traverse = AsyncMock(return_value=mock_traversal_result)
    mock_client.lookup_entity_ids = AsyncMock(return_value=[])

    with (
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
            return_value=mock_client,
        ),
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker",
        ) as MockLinker,
        patch("src.knowledge_graph.nodes.knowledge_graph_node.langfuse", MagicMock()),
    ):
        linker_instance = AsyncMock()
        linker_instance.resolve = AsyncMock(return_value=[_US029_SEED_ID])
        MockLinker.return_value = linker_instance

        state = {
            "ranked_context": ranked_context_with_entity_ids,
            "execution_plan": {"remaining_tokens": 4000},
        }
        result = await knowledge_graph_node(state)

    mock_client.traverse.assert_awaited_once()
    assert result["graph_traversal_skipped"] is False
    assert len(result["graph_context_items"]) == 1


@pytest.mark.asyncio
async def test_graph_results_appended_to_ranked_context_with_source_label(
    ranked_context_with_entity_ids: list,
    mock_traversal_result,
) -> None:
    """AC-4: graph results appended to ranked_context with source='knowledge_graph'."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    mock_client = AsyncMock()
    mock_client.traverse = AsyncMock(return_value=mock_traversal_result)
    mock_client.lookup_entity_ids = AsyncMock(return_value=[])

    with (
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
            return_value=mock_client,
        ),
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker",
        ) as MockLinker,
        patch("src.knowledge_graph.nodes.knowledge_graph_node.langfuse", MagicMock()),
    ):
        linker_instance = AsyncMock()
        linker_instance.resolve = AsyncMock(return_value=[_US029_SEED_ID])
        MockLinker.return_value = linker_instance

        initial_rc_len = len(ranked_context_with_entity_ids)
        state = {
            "ranked_context": ranked_context_with_entity_ids,
            "execution_plan": {"remaining_tokens": 4000},
        }
        result = await knowledge_graph_node(state)

    assert len(result["ranked_context"]) == initial_rc_len + len(mock_traversal_result.items)
    new_items = result["ranked_context"][initial_rc_len:]
    assert all(item["source"] == "knowledge_graph" for item in new_items)


@pytest.mark.asyncio
async def test_node_sets_skipped_true_on_timeout(
    ranked_context_with_entity_ids: list,
) -> None:
    """AC-5: graph_traversal_skipped=True and no raise when traverse() times out."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    mock_client = AsyncMock()
    mock_client.traverse = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_client.lookup_entity_ids = AsyncMock(return_value=[])

    with (
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
            return_value=mock_client,
        ),
        patch(
            "src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker",
        ) as MockLinker,
        patch("src.knowledge_graph.nodes.knowledge_graph_node.langfuse", MagicMock()),
    ):
        linker_instance = AsyncMock()
        linker_instance.resolve = AsyncMock(return_value=[_US029_SEED_ID])
        MockLinker.return_value = linker_instance

        state = {
            "ranked_context": ranked_context_with_entity_ids,
            "execution_plan": {"remaining_tokens": 4000},
        }
        result = await knowledge_graph_node(state)

    assert result["graph_traversal_skipped"] is True
    assert result["graph_tokens_used"] == 0


@pytest.mark.asyncio
async def test_node_skips_traversal_when_budget_is_zero(
    ranked_context_with_entity_ids: list,
) -> None:
    """AC-6: zero remaining_tokens → skip traversal; ranked_context unchanged."""
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    state = {
        "ranked_context": ranked_context_with_entity_ids,
        "execution_plan": {"remaining_tokens": 0},
    }
    result = await knowledge_graph_node(state)

    assert result["graph_traversal_skipped"] is True
    assert result["graph_tokens_used"] == 0
    assert result["ranked_context"] == ranked_context_with_entity_ids
