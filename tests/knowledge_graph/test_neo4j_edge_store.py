"""Tests for Neo4jEdgeStore — TASK-US030-03.

Covers all acceptance criteria using AsyncMock (no live Neo4j in CI):
  AC-2  merge_relationships() groups by edge type and executes UNWIND per type.
  AC-3  delete_entity_relationships() deletes both incoming and outgoing edges.
  AC-5  expire_stale_relationships() loops until batch < 10_000.
  AC-6  Empty list returns 0 without opening a Neo4j session.
  AC-7  ON MATCH does NOT overwrite created_at.
  AC-8  Cypher contains no user-supplied interpolation.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.knowledge_graph.schemas.edge import EdgeType
from src.knowledge_graph.schemas.relationship import GraphRelationship
from src.knowledge_graph.stores.neo4j_edge_store import Neo4jEdgeStore
from src.knowledge_graph.stores.neo4j_store import Neo4jSettings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_CHUNK_ID = UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")
_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_EXPIRES = _NOW + timedelta(days=30)

_FROM_ID = "A" * 16
_TO_ID = "B" * 16


def _make_rel(
    from_id: str = _FROM_ID,
    to_id: str = _TO_ID,
    edge_type: EdgeType = EdgeType.DEPENDS_ON,
    weight: float = 0.9,
) -> GraphRelationship:
    return GraphRelationship(
        from_entity_id=from_id,
        to_entity_id=to_id,
        edge_type=edge_type,
        source_id=_SOURCE_ID,
        chunk_id=_CHUNK_ID,
        weight=weight,
        created_at=_NOW,
        updated_at=_NOW,
        ttl_expires_at=_EXPIRES,
    )


def _make_store(batch_size: int = 100) -> tuple[Neo4jEdgeStore, MagicMock, AsyncMock]:
    """Return (store, mock_driver, mock_session) with patched AsyncGraphDatabase.driver."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    mock_driver.close = AsyncMock()

    settings = Neo4jSettings(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        database="neo4j",
        batch_size=batch_size,
    )

    with patch(
        "src.knowledge_graph.stores.neo4j_edge_store.AsyncGraphDatabase.driver",
        return_value=mock_driver,
    ):
        store = Neo4jEdgeStore(settings=settings)

    return store, mock_driver, mock_session


def _make_result_mock(value: dict) -> AsyncMock:
    """Return an AsyncMock whose async iteration yields a single dict record."""

    async def _aiter(self: object) -> None:  # type: ignore[misc]
        yield value  # type: ignore[misc]

    result_mock = AsyncMock()
    result_mock.__aiter__ = _aiter
    return result_mock


# ---------------------------------------------------------------------------
# merge_relationships — empty list guard (AC-6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_relationships_empty_returns_zero_no_session() -> None:
    """merge_relationships([]) must return 0 without opening a Neo4j session."""
    store, mock_driver, _ = _make_store()
    result = await store.merge_relationships([])
    assert result == 0
    mock_driver.session.assert_not_called()


# ---------------------------------------------------------------------------
# merge_relationships — single relationship (AC-2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_relationships_single_rel_one_run_call() -> None:
    """A single relationship must result in exactly one session.run() call."""
    store, _, mock_session = _make_store()
    rel = _make_rel()

    result = await store.merge_relationships([rel])

    assert result == 1
    assert mock_session.run.call_count == 1


@pytest.mark.asyncio
async def test_merge_relationships_passes_required_props() -> None:
    """session.run() must receive a 'batch' kwarg with all required props."""
    store, _, mock_session = _make_store()
    rel = _make_rel()

    await store.merge_relationships([rel])

    call_kwargs = mock_session.run.call_args
    passed_batch: list[dict] = call_kwargs.kwargs["batch"]
    assert len(passed_batch) == 1
    props = passed_batch[0]
    assert props["from_id"] == rel.from_entity_id
    assert props["to_id"] == rel.to_entity_id
    assert props["source_id"] == str(rel.source_id)
    assert props["chunk_id"] == str(rel.chunk_id)
    assert props["weight"] == rel.weight
    assert props["created_at"] == rel.created_at.isoformat()
    assert props["updated_at"] == rel.updated_at.isoformat()
    assert props["ttl_expires_at"] == rel.ttl_expires_at.isoformat()


# ---------------------------------------------------------------------------
# merge_relationships — grouping by edge type (AC-2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_relationships_groups_by_edge_type() -> None:
    """Relationships of different edge types must each produce a separate run() call."""
    store, _, mock_session = _make_store()
    rel_depends = _make_rel(edge_type=EdgeType.DEPENDS_ON)
    rel_owned = _make_rel(
        from_id="C" * 16,
        to_id="D" * 16,
        edge_type=EdgeType.OWNED_BY,
    )

    result = await store.merge_relationships([rel_depends, rel_owned])

    assert result == 2
    # Two distinct edge types → two separate UNWIND calls
    assert mock_session.run.call_count == 2


@pytest.mark.asyncio
async def test_merge_relationships_same_edge_type_one_run_call() -> None:
    """Two relationships of the same edge type must be batched into a single run()."""
    store, _, mock_session = _make_store()
    rel_a = _make_rel(from_id="A" * 16, to_id="B" * 16, edge_type=EdgeType.REFERENCES)
    rel_b = _make_rel(from_id="C" * 16, to_id="D" * 16, edge_type=EdgeType.REFERENCES)

    result = await store.merge_relationships([rel_a, rel_b])

    assert result == 2
    assert mock_session.run.call_count == 1
    passed_batch: list[dict] = mock_session.run.call_args.kwargs["batch"]
    assert len(passed_batch) == 2


# ---------------------------------------------------------------------------
# merge_relationships — sub-batching (AC-2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_relationships_sub_batching() -> None:
    """batch_size=2 with 5 same-type relationships must produce ceil(5/2)=3 run() calls."""
    store, _, mock_session = _make_store(batch_size=2)
    from_ids = [chr(ord("A") + i) * 16 for i in range(5)]
    to_ids = [chr(ord("a") + i) * 16 for i in range(5)]
    relationships = [
        _make_rel(from_id=f, to_id=t, edge_type=EdgeType.DEPLOYED_BY)
        for f, t in zip(from_ids, to_ids, strict=True)
    ]

    result = await store.merge_relationships(relationships)

    assert result == 5
    assert mock_session.run.call_count == 3  # ceil(5/2) = 3


# ---------------------------------------------------------------------------
# merge_relationships — Cypher label safety (AC-8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_relationships_cypher_label_from_enum_only() -> None:
    """The UNWIND query must contain the enum label, not user-supplied strings."""
    store, _, mock_session = _make_store()
    rel = _make_rel(edge_type=EdgeType.HAS_INCIDENT)

    await store.merge_relationships([rel])

    cypher: str = mock_session.run.call_args.args[0]
    assert "HAS_INCIDENT" in cypher
    # The batch param carries from_id/to_id as $params — not interpolated
    assert "$batch" in cypher
    assert "props.from_id" in cypher
    assert "props.to_id" in cypher


@pytest.mark.asyncio
async def test_merge_relationships_on_match_no_created_at(  # AC-7
) -> None:
    """ON MATCH block must NOT reference created_at to preserve original value."""
    store, _, mock_session = _make_store()
    rel = _make_rel()

    await store.merge_relationships([rel])

    cypher: str = mock_session.run.call_args.args[0]
    # Split into ON CREATE and ON MATCH blocks to check each independently.
    on_create_block, on_match_block = cypher.split("ON MATCH SET", 1)
    # ON CREATE must include created_at
    assert "created_at" in on_create_block
    # ON MATCH must NOT set created_at
    assert "created_at" not in on_match_block


# ---------------------------------------------------------------------------
# delete_entity_relationships (AC-3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_entity_relationships_returns_count() -> None:
    """delete_entity_relationships() must return the count from the Cypher result."""
    store, _, mock_session = _make_store()
    mock_result = _make_result_mock({"total": 7})
    mock_session.run.return_value = mock_result

    count = await store.delete_entity_relationships("E" * 16)

    assert count == 7
    assert mock_session.run.call_count == 1


@pytest.mark.asyncio
async def test_delete_entity_relationships_passes_entity_id() -> None:
    """entity_id must be passed as a $-parameter, not interpolated into Cypher."""
    store, _, mock_session = _make_store()
    mock_result = _make_result_mock({"total": 0})
    mock_session.run.return_value = mock_result

    await store.delete_entity_relationships("F" * 16)

    cypher: str = mock_session.run.call_args.args[0]
    kwargs: dict = mock_session.run.call_args.kwargs
    assert "$entity_id" in cypher
    assert kwargs.get("entity_id") == "F" * 16


@pytest.mark.asyncio
async def test_delete_entity_relationships_matches_both_directions() -> None:
    """Cypher must match both incoming and outgoing relationships: (n)-[r]-()."""
    store, _, mock_session = _make_store()
    mock_result = _make_result_mock({"total": 0})
    mock_session.run.return_value = mock_result

    await store.delete_entity_relationships("G" * 16)

    cypher: str = mock_session.run.call_args.args[0]
    # Undirected pattern covers both incoming and outgoing
    assert "-[r]-" in cypher or "-[r]-(" in cypher


@pytest.mark.asyncio
async def test_delete_entity_relationships_returns_zero_on_empty_result() -> None:
    """delete_entity_relationships() must return 0 when result set is empty."""
    store, _, mock_session = _make_store()

    async def _empty_aiter(self: object) -> None:  # type: ignore[misc]
        return
        yield  # type: ignore[misc]

    empty_result = AsyncMock()
    empty_result.__aiter__ = _empty_aiter
    mock_session.run.return_value = empty_result

    count = await store.delete_entity_relationships("H" * 16)
    assert count == 0


# ---------------------------------------------------------------------------
# expire_stale_relationships (AC-5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expire_stale_relationships_single_batch() -> None:
    """expire_stale_relationships() must stop after one batch when deleted < 10_000."""
    store, _, mock_session = _make_store()
    mock_result = _make_result_mock({"deleted": 42})
    mock_session.run.return_value = mock_result

    cutoff = _NOW
    total = await store.expire_stale_relationships(cutoff)

    assert total == 42
    # Only one batch needed (42 < 10_000)
    assert mock_session.run.call_count == 1


@pytest.mark.asyncio
async def test_expire_stale_relationships_multiple_batches() -> None:
    """expire_stale_relationships() must loop while deleted == 10_000 and stop when < 10_000."""
    store, _, mock_session = _make_store()

    # First two calls return full batch; third call signals done
    full_batch = _make_result_mock({"deleted": 10_000})
    partial_batch = _make_result_mock({"deleted": 999})

    call_count = 0

    async def _side_effect(*args: object, **kwargs: object) -> AsyncMock:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return full_batch
        return partial_batch

    mock_session.run.side_effect = _side_effect

    total = await store.expire_stale_relationships(_NOW)

    assert total == 10_000 + 10_000 + 999
    assert mock_session.run.call_count == 3


@pytest.mark.asyncio
async def test_expire_stale_relationships_cutoff_is_param() -> None:
    """cutoff must be passed as a $-parameter, not interpolated into Cypher."""
    store, _, mock_session = _make_store()
    mock_result = _make_result_mock({"deleted": 0})
    mock_session.run.return_value = mock_result

    cutoff = _NOW
    await store.expire_stale_relationships(cutoff)

    cypher: str = mock_session.run.call_args.args[0]
    kwargs: dict = mock_session.run.call_args.kwargs
    assert "$cutoff" in cypher
    assert kwargs.get("cutoff") == cutoff.isoformat()


@pytest.mark.asyncio
async def test_expire_stale_relationships_returns_zero_when_nothing_deleted() -> None:
    """expire_stale_relationships() must return 0 when no stale relationships exist."""
    store, _, mock_session = _make_store()
    mock_result = _make_result_mock({"deleted": 0})
    mock_session.run.return_value = mock_result

    total = await store.expire_stale_relationships(_NOW)

    assert total == 0
    assert mock_session.run.call_count == 1


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_calls_driver_close() -> None:
    """close() must delegate to the underlying driver.close()."""
    store, mock_driver, _ = _make_store()
    await store.close()
    mock_driver.close.assert_awaited_once()
