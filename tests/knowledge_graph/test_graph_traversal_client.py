"""Tests for GraphTraversalClient — TASK-US029-03.

Covers all acceptance criteria using AsyncMock (no live Neo4j in CI):
  AC-1  traverse() raises asyncio.TimeoutError when query exceeds query_timeout_s.
  AC-2  Duplicate entity_id rows are deduplicated — each entity appears at most once.
  AC-3  Results are sorted ascending by hops before budget truncation.
  AC-4  _apply_budget with token_budget=0 returns ([], True, 0) without error.
  AC-5  GraphTraversalResult.truncated=True when budget exhausted before all items.
  AC-6  lookup_entity_ids() case-normalises names before querying.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.knowledge_graph.schemas.edge import EdgeType
from src.knowledge_graph.stores.neo4j_store import Neo4jSettings
from src.knowledge_graph.traversal.neo4j_traversal_client import GraphTraversalClient
from src.knowledge_graph.traversal.schemas import (
    GraphContextItem,
    TraversalConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SETTINGS = Neo4jSettings(
    uri="bolt://localhost:7687",
    username="neo4j",
    password="password",
    database="neo4j",
    batch_size=100,
)

_SEED_IDS = ["entity-001"]


def _make_config(
    seed_entity_ids: list[str] = _SEED_IDS,
    token_budget: int = 2000,
    max_depth: int = 2,
) -> TraversalConfig:
    return TraversalConfig(
        seed_entity_ids=seed_entity_ids,
        edge_types=list(EdgeType),
        max_depth=max_depth,
        max_nodes_per_seed=50,
        token_budget=token_budget,
    )


async def _aiter_records(records: list[dict]) -> AsyncGenerator[dict, None]:
    """Async generator that yields plain dicts, simulating Neo4j result iteration."""
    for record in records:
        yield record


def _make_client(rows: list[dict]) -> tuple[GraphTraversalClient, AsyncMock]:
    """Build a ``GraphTraversalClient`` with a fully mocked Neo4j driver.

    Returns (client, mock_session) so tests can inspect call arguments.
    The mock session's ``run()`` returns an async iterable over ``rows``.
    """
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock(return_value=_aiter_records(rows))

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    mock_driver.close = AsyncMock()

    with patch(
        "src.knowledge_graph.traversal.neo4j_traversal_client.AsyncGraphDatabase.driver",
        return_value=mock_driver,
    ):
        client = GraphTraversalClient(settings=_SETTINGS)

    return client, mock_session


# ---------------------------------------------------------------------------
# AC-1 — timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traverse_raises_timeout_error_when_query_exceeds_budget() -> None:
    """traverse() must raise asyncio.TimeoutError when Neo4j query exceeds query_timeout_s."""

    async def _slow_aiter() -> AsyncGenerator[dict, None]:
        await asyncio.sleep(1.0)  # outlasts 0.5 s timeout
        yield {}  # pragma: no cover

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.run = AsyncMock(return_value=_slow_aiter())

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session

    # Attach query_timeout_s to settings so the client uses 0.05 s (fast test)
    settings = Neo4jSettings(uri="bolt://localhost:7687", username="neo4j", password="pw")
    settings.__dict__["query_timeout_s"] = 0.05  # inject without subclassing

    with patch(
        "src.knowledge_graph.traversal.neo4j_traversal_client.AsyncGraphDatabase.driver",
        return_value=mock_driver,
    ):
        client = GraphTraversalClient(settings=settings)

    with pytest.raises(asyncio.TimeoutError):
        await client.traverse(_make_config())


# ---------------------------------------------------------------------------
# AC-2 — deduplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traverse_deduplicates_duplicate_entity_ids() -> None:
    """Duplicate entity_id rows must produce exactly one GraphContextItem."""
    rows = [
        {
            "entity_id": "svc-001",
            "entity_type": "Service",
            "name": "auth-service",
            "hops": 1,
            "path_summary": "seed -[DEPENDS_ON]-> auth-service",
            "properties": {},
        },
        # Exact duplicate — same entity_id, different name field (should be ignored)
        {
            "entity_id": "svc-001",
            "entity_type": "Service",
            "name": "auth-service-duplicate",
            "hops": 2,
            "path_summary": "seed -[REFERENCES]-> auth-service",
            "properties": {},
        },
    ]
    client, _ = _make_client(rows)
    result = await client.traverse(_make_config())

    entity_ids = [item.entity_id for item in result.items]
    assert entity_ids.count("svc-001") == 1


# ---------------------------------------------------------------------------
# AC-3 — hop-ascending sort
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traverse_results_sorted_ascending_by_hops() -> None:
    """Items must be sorted ascending by hops before budget truncation."""
    rows = [
        {
            "entity_id": "far-001",
            "entity_type": "Service",
            "name": "far",
            "hops": 3,
            "path_summary": "seed -> mid -> far",
            "properties": {},
        },
        {
            "entity_id": "close-001",
            "entity_type": "Service",
            "name": "close",
            "hops": 1,
            "path_summary": "seed -> close",
            "properties": {},
        },
        {
            "entity_id": "mid-001",
            "entity_type": "Service",
            "name": "mid",
            "hops": 2,
            "path_summary": "seed -> close -> mid",
            "properties": {},
        },
    ]
    client, _ = _make_client(rows)
    result = await client.traverse(_make_config(token_budget=5000))

    hops_sequence = [item.hops for item in result.items]
    assert hops_sequence == sorted(hops_sequence)


# ---------------------------------------------------------------------------
# AC-4 — _apply_budget with token_budget=0
# ---------------------------------------------------------------------------


def test_apply_budget_zero_budget_returns_empty_truncated() -> None:
    """_apply_budget(token_budget=0) must return ([], True, 0) for non-empty input."""
    with patch(
        "src.knowledge_graph.traversal.neo4j_traversal_client.AsyncGraphDatabase.driver",
        return_value=MagicMock(),
    ):
        client = GraphTraversalClient(settings=_SETTINGS)

    items = [
        GraphContextItem(
            entity_id="x",
            entity_type="Service",
            name="x",
            hops=1,
            path_summary="",
            token_count=10,
        )
    ]
    included, truncated, total = client._apply_budget(items, token_budget=0)

    assert included == []
    assert truncated is True
    assert total == 0


def test_apply_budget_zero_budget_empty_items_not_truncated() -> None:
    """_apply_budget(token_budget=0) on empty items returns ([], False, 0)."""
    with patch(
        "src.knowledge_graph.traversal.neo4j_traversal_client.AsyncGraphDatabase.driver",
        return_value=MagicMock(),
    ):
        client = GraphTraversalClient(settings=_SETTINGS)

    included, truncated, total = client._apply_budget([], token_budget=0)

    assert included == []
    assert truncated is False
    assert total == 0


# ---------------------------------------------------------------------------
# AC-5 — truncated flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traverse_truncated_true_when_budget_exhausted() -> None:
    """GraphTraversalResult.truncated must be True when budget runs out before all items."""
    # Each item will have text_repr long enough to exceed a tiny budget.
    rows = [
        {
            "entity_id": f"svc-{i:03d}",
            "entity_type": "Service",
            "name": f"service-{i}",
            "hops": 1,
            "path_summary": f"seed -> service-{i}",
            "properties": {},
        }
        for i in range(20)
    ]
    client, _ = _make_client(rows)
    # Use a very small budget so not all items fit.
    result = await client.traverse(_make_config(token_budget=5))

    assert result.truncated is True
    assert len(result.items) < 20


@pytest.mark.asyncio
async def test_traverse_truncated_false_when_all_items_fit() -> None:
    """GraphTraversalResult.truncated must be False when all items fit within budget."""
    rows = [
        {
            "entity_id": "svc-001",
            "entity_type": "Service",
            "name": "auth",
            "hops": 1,
            "path_summary": "seed -> auth",
            "properties": {},
        }
    ]
    client, _ = _make_client(rows)
    result = await client.traverse(_make_config(token_budget=9999))

    assert result.truncated is False
    assert len(result.items) == 1


# ---------------------------------------------------------------------------
# AC-6 — lookup_entity_ids case-normalisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_entity_ids_case_normalises_names() -> None:
    """lookup_entity_ids(['Auth Service']) must query with ['auth service']."""
    rows = [{"entity_id": "svc-abc"}]
    client, mock_session = _make_client(rows)
    # Reset mock so lookup uses a fresh async iterator
    mock_session.run = AsyncMock(return_value=_aiter_records(rows))

    result = await client.lookup_entity_ids(["Auth Service", " USER-REPO "])

    assert result == ["svc-abc"]
    call_kwargs = mock_session.run.call_args
    names_lower = call_kwargs.kwargs["names_lower"]
    assert "auth service" in names_lower
    assert "user-repo" in names_lower


@pytest.mark.asyncio
async def test_lookup_entity_ids_empty_list_returns_empty() -> None:
    """lookup_entity_ids([]) must return [] without opening a Neo4j session."""
    client, mock_session = _make_client([])

    result = await client.lookup_entity_ids([])

    assert result == []
    mock_session.run.assert_not_called()


# ---------------------------------------------------------------------------
# Misc — close()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_calls_driver_close() -> None:
    """close() must call the underlying driver's close() method."""
    mock_driver = MagicMock()
    mock_driver.close = AsyncMock()

    with patch(
        "src.knowledge_graph.traversal.neo4j_traversal_client.AsyncGraphDatabase.driver",
        return_value=mock_driver,
    ):
        client = GraphTraversalClient(settings=_SETTINGS)

    await client.close()
    mock_driver.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# seeds_used in result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traverse_result_seeds_used_matches_config() -> None:
    """GraphTraversalResult.seeds_used must equal the config seed_entity_ids."""
    seed_ids = ["seed-A", "seed-B"]
    client, _ = _make_client([])
    result = await client.traverse(_make_config(seed_entity_ids=seed_ids, token_budget=1000))

    assert result.seeds_used == seed_ids


# ---------------------------------------------------------------------------
# TASK-US029-05 — AC-5/AC-6 named tests
# ---------------------------------------------------------------------------

_US029_SEED_ID = "a3f1c2b4d5e6f708"


@pytest.mark.asyncio
async def test_traversal_client_raises_timeout_when_neo4j_is_slow() -> None:
    """AC-5: traverse() raises asyncio.TimeoutError when query exceeds query_timeout_s."""

    async def slow_neo4j(*args: object, **kwargs: object) -> list:
        await asyncio.sleep(10)
        return []  # pragma: no cover

    config = TraversalConfig(seed_entity_ids=[_US029_SEED_ID], token_budget=1000)

    with (
        patch(
            "src.knowledge_graph.traversal.neo4j_traversal_client.GraphTraversalClient._run_query",
            side_effect=slow_neo4j,
        ),
        patch(
            "src.knowledge_graph.traversal.neo4j_traversal_client.AsyncGraphDatabase.driver",
            return_value=MagicMock(),
        ),
    ):
        client = GraphTraversalClient(settings=_SETTINGS)
        # Override query_timeout_s to 0.05 s so the test completes quickly
        client._settings = MagicMock(
            uri="bolt://localhost:7687",
            username="neo4j",
            password="password",
            database="neo4j",
            query_timeout_s=0.05,
        )
        with pytest.raises(asyncio.TimeoutError):
            await client.traverse(config)


def test_apply_budget_truncates_items(make_graph_item) -> None:
    """AC-6: _apply_budget stops when adding the next item would exceed the budget."""
    client = GraphTraversalClient.__new__(GraphTraversalClient)
    items = [make_graph_item(entity_id=str(i) * 16, tokens=40) for i in range(5)]
    included, truncated, total = client._apply_budget(items, token_budget=100)

    assert len(included) == 2  # 40 + 40 = 80 ≤ 100; third would make 120 > 100
    assert truncated is True
    assert total == 80


def test_apply_budget_no_truncation_when_budget_sufficient(make_graph_item) -> None:
    """AC-6: _apply_budget includes all items when budget covers the full list."""
    client = GraphTraversalClient.__new__(GraphTraversalClient)
    items = [make_graph_item(entity_id=str(i) * 16, tokens=10) for i in range(5)]
    included, truncated, total = client._apply_budget(items, token_budget=100)

    assert len(included) == 5
    assert truncated is False
    assert total == 50
