"""Tests for Neo4jEntityStore — TASK-US028-03.

Covers all acceptance criteria using AsyncMock (no live Neo4j in CI):
  AC-3  Node properties include all required fields.
  AC-4  Duplicate entity_id across two calls triggers MERGE (one node).
  AC-5  updated_at set on ON MATCH; created_at set only on ON CREATE.
  AC-6  All 7 entity type labels receive uniqueness constraints.
  AC-7  merge_entities([]) returns immediately without opening a session.
  AC-8  apply_constraints() called twice does not raise.
  AC-9  Dynamic Cypher label comes only from EntityType enum values.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.knowledge_graph.schemas.entity import EntityType, ExtractedEntity, make_entity_id
from src.knowledge_graph.stores.constraints import CONSTRAINT_STATEMENTS, ENTITY_TYPES
from src.knowledge_graph.stores.neo4j_store import Neo4jEntityStore, Neo4jSettings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_CHUNK_ID = UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")
_NOW = datetime.now(tz=UTC)


def _make_entity(
    canonical: str = "auth service",
    entity_type: EntityType = EntityType.SERVICE,
    name: str = "Auth Service",
) -> ExtractedEntity:
    return ExtractedEntity(
        entity_id=make_entity_id(entity_type, canonical),
        entity_type=entity_type,
        name=name,
        canonical_name=canonical,
        source_id=_SOURCE_ID,
        chunk_id=_CHUNK_ID,
        created_at=_NOW,
    )


def _make_store() -> tuple[Neo4jEntityStore, MagicMock, AsyncMock]:
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
        batch_size=100,
    )

    with patch(
        "src.knowledge_graph.stores.neo4j_store.AsyncGraphDatabase.driver",
        return_value=mock_driver,
    ):
        store = Neo4jEntityStore(settings=settings)

    return store, mock_driver, mock_session


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


def test_constraint_statements_cover_all_seven_labels() -> None:
    """All 7 EntityType labels must receive their own uniqueness constraint."""
    assert len(ENTITY_TYPES) == 7
    assert set(ENTITY_TYPES) == {
        "Service",
        "Repository",
        "Developer",
        "Incident",
        "Deployment",
        "AlertRule",
        "Document",
    }
    assert len(CONSTRAINT_STATEMENTS) == 7
    for stmt in CONSTRAINT_STATEMENTS:
        assert "CREATE CONSTRAINT IF NOT EXISTS" in stmt
        assert "REQUIRE n.entity_id IS UNIQUE" in stmt


@pytest.mark.asyncio
async def test_apply_constraints_runs_all_statements() -> None:
    """apply_constraints() must execute one statement per entity type label."""
    store, _, mock_session = _make_store()
    await store.apply_constraints()

    assert mock_session.run.call_count == len(CONSTRAINT_STATEMENTS)
    executed = [call.args[0] for call in mock_session.run.call_args_list]
    for stmt in CONSTRAINT_STATEMENTS:
        assert stmt in executed


@pytest.mark.asyncio
async def test_apply_constraints_idempotent_two_calls() -> None:
    """apply_constraints() called twice must not raise (IF NOT EXISTS)."""
    store, _, mock_session = _make_store()
    await store.apply_constraints()
    await store.apply_constraints()
    # 7 statements × 2 calls = 14
    assert mock_session.run.call_count == len(CONSTRAINT_STATEMENTS) * 2


# ---------------------------------------------------------------------------
# merge_entities — empty list guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_entities_empty_list_no_session_opened() -> None:
    """merge_entities([]) must return immediately without opening a Neo4j session."""
    store, mock_driver, _ = _make_store()
    await store.merge_entities([])
    mock_driver.session.assert_not_called()


# ---------------------------------------------------------------------------
# merge_entities — required node properties
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_entities_passes_required_props() -> None:
    """Node properties must include entity_id, type, name, source_id, created_at."""
    store, _, mock_session = _make_store()
    entity = _make_entity()

    await store.merge_entities([entity])

    assert mock_session.run.call_count == 1
    call_kwargs = mock_session.run.call_args
    passed_batch: list[dict] = call_kwargs.kwargs["batch"]
    assert len(passed_batch) == 1
    props = passed_batch[0]
    assert props["entity_id"] == entity.entity_id
    assert props["type"] == entity.entity_type.value
    assert props["name"] == entity.name
    assert props["source_id"] == str(entity.source_id)
    assert "created_at" in props
    assert "updated_at" in props


# ---------------------------------------------------------------------------
# merge_entities — deduplication (MERGE on entity_id)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_entities_same_entity_id_one_run_call() -> None:
    """Two entities with the same entity_id in one call must be grouped into one batch run.

    Because they share the same entity_type label, they go into the same sub-batch,
    resulting in a single session.run() call for that label — MERGE handles dedup at DB level.
    """
    store, _, mock_session = _make_store()
    entity_a = _make_entity(canonical="auth service", name="Auth Service")
    entity_b = _make_entity(canonical="auth service", name="Auth Service v2")
    # Both have the same entity_id (same type + canonical_name)
    assert entity_a.entity_id == entity_b.entity_id

    await store.merge_entities([entity_a, entity_b])

    # One label group → one session.run() call containing both props
    assert mock_session.run.call_count == 1
    passed_batch = mock_session.run.call_args.kwargs["batch"]
    assert len(passed_batch) == 2


@pytest.mark.asyncio
async def test_merge_entities_separate_calls_same_entity_id() -> None:
    """Two separate merge_entities() calls for the same entity_id each trigger one run()."""
    store, _, mock_session = _make_store()
    entity = _make_entity()

    await store.merge_entities([entity])
    await store.merge_entities([entity])

    # Each call opens its own session context → 2 run() calls total (MERGE deduplicates at DB)
    assert mock_session.run.call_count == 2


# ---------------------------------------------------------------------------
# merge_entities — grouping by entity type label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_entities_groups_by_label() -> None:
    """Entities of different types must each produce a separate session.run() call."""
    store, _, mock_session = _make_store()
    svc = _make_entity(canonical="gateway", entity_type=EntityType.SERVICE, name="Gateway")
    repo = _make_entity(canonical="gateway", entity_type=EntityType.REPOSITORY, name="gateway-repo")

    await store.merge_entities([svc, repo])

    # Two distinct labels → two run() calls
    assert mock_session.run.call_count == 2


# ---------------------------------------------------------------------------
# merge_entities — sub-batching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_entities_sub_batching() -> None:
    """batch_size=2 with 5 entities of the same type must produce ceil(5/2)=3 run() calls."""
    settings = Neo4jSettings(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        database="neo4j",
        batch_size=2,
    )
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session

    with patch(
        "src.knowledge_graph.stores.neo4j_store.AsyncGraphDatabase.driver",
        return_value=mock_driver,
    ):
        store = Neo4jEntityStore(settings=settings)

    entities = [
        _make_entity(canonical=f"service {i}", name=f"Service {i}")
        for i in range(5)
    ]
    await store.merge_entities(entities)

    assert mock_session.run.call_count == 3  # ceil(5/2) = 3


# ---------------------------------------------------------------------------
# merge_entities — updated_at / created_at Cypher structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_entities_cypher_contains_on_match_updated_at() -> None:
    """The Cypher statement must set updated_at on ON MATCH and created_at on ON CREATE."""
    store, _, mock_session = _make_store()
    await store.merge_entities([_make_entity()])

    cypher: str = mock_session.run.call_args.args[0]
    assert "ON MATCH" in cypher
    assert "updated_at" in cypher
    assert "ON CREATE" in cypher
    assert "created_at" in cypher


# ---------------------------------------------------------------------------
# merge_entities — dynamic label safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_entities_label_comes_from_entity_type_value() -> None:
    """The Cypher label must match the EntityType enum value exactly."""
    store, _, mock_session = _make_store()
    entity = _make_entity(entity_type=EntityType.INCIDENT, canonical="p0 outage", name="P0 Outage")
    await store.merge_entities([entity])

    cypher: str = mock_session.run.call_args.args[0]
    assert "Incident" in cypher


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_calls_driver_close() -> None:
    """close() must delegate to the underlying driver."""
    store, mock_driver, _ = _make_store()
    await store.close()
    mock_driver.close.assert_awaited_once()
