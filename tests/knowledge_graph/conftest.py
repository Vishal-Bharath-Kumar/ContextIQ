"""Shared pytest fixtures for knowledge_graph tests — TASK-US028-05.

Provides reusable fixtures consumed across:
  test_entity_schema.py     — AC-4 (deterministic entity_id)
  test_entity_extractor.py  — AC-2, AC-5 (extraction + timing)
  test_neo4j_entity_store.py — AC-3, AC-4 (node write + dedup)
  test_entity_consumer.py   — AC-1, AC-6 (Kafka routing + retry)
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.knowledge_graph.schemas.entity import (
    EntityType,
    ExtractedEntity,
    make_entity_id,
)
from src.knowledge_graph.schemas.events import ChunkIndexedEvent

SOURCE_ID = uuid4()
CHUNK_ID = uuid4()


@pytest.fixture
def chunk_indexed_event() -> ChunkIndexedEvent:
    return ChunkIndexedEvent(
        chunk_id=CHUNK_ID,
        source_id=SOURCE_ID,
        tenant_id="acme",
        document_id="github:org/repo:abc123",
        text="The auth-service depends on the user-repository owned by @alice.",
        token_count=14,
        embedding_model="text-embedding-3-small",
        indexed_at=datetime.now(tz=UTC),
    )


@pytest.fixture
def make_entity() -> Callable[..., ExtractedEntity]:
    def _make(
        entity_type: EntityType = EntityType.SERVICE,
        name: str = "auth-service",
    ) -> ExtractedEntity:
        canonical = name.strip().lower()
        return ExtractedEntity(
            entity_id=make_entity_id(entity_type, canonical),
            entity_type=entity_type,
            name=name,
            canonical_name=canonical,
            source_id=SOURCE_ID,
            chunk_id=CHUNK_ID,
            created_at=datetime.now(tz=UTC),
        )

    return _make


# ---------------------------------------------------------------------------
# TASK-US029-05 shared fixtures
# ---------------------------------------------------------------------------

SEED_ID = "a3f1c2b4d5e6f708"
TENANT = "acme"


@pytest.fixture
def make_graph_item():
    from src.knowledge_graph.traversal.schemas import GraphContextItem

    def _make(
        entity_id: str = SEED_ID,
        hops: int = 1,
        name: str = "auth-service",
        tokens: int = 30,
    ) -> GraphContextItem:
        return GraphContextItem(
            entity_id=entity_id,
            entity_type="Service",
            name=name,
            hops=hops,
            path_summary=f"seed -[DEPENDS_ON]-> {name}",
            token_count=tokens,
        )

    return _make


@pytest.fixture
def mock_traversal_result(make_graph_item):
    from src.knowledge_graph.traversal.schemas import GraphTraversalResult

    item = make_graph_item()
    return GraphTraversalResult(
        items=[item],
        total_tokens=30,
        query_duration_ms=120.0,
        seeds_used=[SEED_ID],
        truncated=False,
    )


@pytest.fixture
def ranked_context_with_entity_ids():
    return [
        {
            "text": "auth-service depends on user-repository",
            "score": 0.95,
            "source_id": str(uuid4()),
            "metadata": {"entity_ids": [SEED_ID]},
        }
    ]


@pytest.fixture
def ranked_context_no_entity_ids():
    return [
        {
            "text": "the auth service had an outage last week",
            "score": 0.80,
            "source_id": str(uuid4()),
            "metadata": {},
        }
    ]
