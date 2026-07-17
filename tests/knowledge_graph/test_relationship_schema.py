"""Tests for graph relationship schemas — TASK-US030-01.

Covers all acceptance criteria:
  AC-1  GraphRelationship with from_entity_id == to_entity_id raises ValidationError.
  AC-2  GraphRelationship.create() sets ttl_expires_at = created_at + timedelta(days=ttl_days).
  AC-3  RelationshipExpirySettings(ttl_days=7).ttl_delta == timedelta(days=7).
  AC-4  TombstoneEvent and GraphUpdatedEvent have ConfigDict(frozen=True).
  AC-5  GraphUpdatedEvent.event_type defaults to "knowledge_graph_updated".
  AC-6  TombstoneEvent.event_type defaults to "knowledge_entity_tombstone".
  AC-7  GraphRelationship.weight is clamped to [0, 1].
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.knowledge_graph.schemas.edge import EdgeType
from src.knowledge_graph.schemas.events import GraphUpdatedEvent, TombstoneEvent
from src.knowledge_graph.schemas.relationship import (
    GraphRelationship,
    RelationshipExpirySettings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_CHUNK_ID = UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")
_FROM_ID = "a" * 16
_TO_ID = "b" * 16
_NOW = datetime.now(tz=UTC)


def _make_relationship(**overrides: object) -> GraphRelationship:
    return GraphRelationship.create(
        from_entity_id=overrides.get("from_entity_id", _FROM_ID),  # type: ignore[arg-type]
        to_entity_id=overrides.get("to_entity_id", _TO_ID),  # type: ignore[arg-type]
        edge_type=overrides.get("edge_type", EdgeType.DEPENDS_ON),  # type: ignore[arg-type]
        source_id=overrides.get("source_id", _SOURCE_ID),  # type: ignore[arg-type]
        chunk_id=overrides.get("chunk_id", _CHUNK_ID),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# AC-1 — self-loop validation
# ---------------------------------------------------------------------------


def test_graph_relationship_rejects_self_loop() -> None:
    """from_entity_id == to_entity_id must raise ValidationError."""
    with pytest.raises(ValidationError, match="Self-loop relationship not allowed"):
        GraphRelationship.create(
            from_entity_id=_FROM_ID,
            to_entity_id=_FROM_ID,
            edge_type=EdgeType.DEPENDS_ON,
            source_id=_SOURCE_ID,
            chunk_id=_CHUNK_ID,
        )


# ---------------------------------------------------------------------------
# AC-2 — ttl_expires_at computation
# ---------------------------------------------------------------------------


def test_graph_relationship_create_sets_ttl_expires_at() -> None:
    """ttl_expires_at must equal created_at + timedelta(days=ttl_days)."""
    rel = GraphRelationship.create(
        from_entity_id=_FROM_ID,
        to_entity_id=_TO_ID,
        edge_type=EdgeType.OWNED_BY,
        source_id=_SOURCE_ID,
        chunk_id=_CHUNK_ID,
        ttl_days=15,
    )
    delta = rel.ttl_expires_at - rel.created_at
    assert delta == timedelta(days=15)


def test_graph_relationship_create_sets_default_ttl() -> None:
    """Default ttl_days=30 is applied when not specified."""
    rel = _make_relationship()
    delta = rel.ttl_expires_at - rel.created_at
    assert delta == timedelta(days=30)


def test_graph_relationship_create_sets_updated_at_equal_to_created_at() -> None:
    """created_at and updated_at are both set to now at creation time."""
    rel = _make_relationship()
    assert rel.created_at == rel.updated_at


# ---------------------------------------------------------------------------
# AC-3 — RelationshipExpirySettings.ttl_delta
# ---------------------------------------------------------------------------


def test_relationship_expiry_settings_ttl_delta_matches_ttl_days() -> None:
    settings = RelationshipExpirySettings(ttl_days=7)
    assert settings.ttl_delta == timedelta(days=7)


def test_relationship_expiry_settings_default_ttl_days() -> None:
    settings = RelationshipExpirySettings()
    assert settings.ttl_days == 30
    assert settings.ttl_delta == timedelta(days=30)


# ---------------------------------------------------------------------------
# AC-4 — frozen=True for new event classes
# ---------------------------------------------------------------------------


def test_tombstone_event_is_frozen() -> None:
    event = TombstoneEvent(
        entity_id=_FROM_ID,
        source_id=_SOURCE_ID,
        tenant_id="tenant-1",
        document_id="doc-abc",
        deleted_at=_NOW,
    )
    with pytest.raises((TypeError, ValidationError)):
        event.tenant_id = "other"  # type: ignore[misc]


def test_graph_updated_event_is_frozen() -> None:
    event = GraphUpdatedEvent(
        source_id=_SOURCE_ID,
        tenant_id="tenant-1",
        chunks_processed=10,
        entities_upserted=5,
        relationships_upserted=3,
        relationships_expired=1,
        updated_at=_NOW,
    )
    with pytest.raises((TypeError, ValidationError)):
        event.tenant_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC-5 — GraphUpdatedEvent default event_type
# ---------------------------------------------------------------------------


def test_graph_updated_event_default_event_type() -> None:
    event = GraphUpdatedEvent(
        source_id=_SOURCE_ID,
        tenant_id="tenant-1",
        chunks_processed=1,
        entities_upserted=1,
        relationships_upserted=1,
        relationships_expired=0,
        updated_at=_NOW,
    )
    assert event.event_type == "knowledge_graph_updated"


# ---------------------------------------------------------------------------
# AC-6 — TombstoneEvent default event_type
# ---------------------------------------------------------------------------


def test_tombstone_event_default_event_type() -> None:
    event = TombstoneEvent(
        entity_id=_FROM_ID,
        source_id=_SOURCE_ID,
        tenant_id="tenant-1",
        document_id="doc-xyz",
        deleted_at=_NOW,
    )
    assert event.event_type == "knowledge_entity_tombstone"


# ---------------------------------------------------------------------------
# AC-7 — weight validation
# ---------------------------------------------------------------------------


def test_graph_relationship_weight_below_zero_raises() -> None:
    with pytest.raises(ValidationError):
        GraphRelationship(
            from_entity_id=_FROM_ID,
            to_entity_id=_TO_ID,
            edge_type=EdgeType.REFERENCES,
            source_id=_SOURCE_ID,
            chunk_id=_CHUNK_ID,
            weight=-0.1,
            created_at=_NOW,
            updated_at=_NOW,
            ttl_expires_at=_NOW + timedelta(days=30),
        )


def test_graph_relationship_weight_above_one_raises() -> None:
    with pytest.raises(ValidationError):
        GraphRelationship(
            from_entity_id=_FROM_ID,
            to_entity_id=_TO_ID,
            edge_type=EdgeType.REFERENCES,
            source_id=_SOURCE_ID,
            chunk_id=_CHUNK_ID,
            weight=1.1,
            created_at=_NOW,
            updated_at=_NOW,
            ttl_expires_at=_NOW + timedelta(days=30),
        )


def test_graph_relationship_valid_weight_boundary_values() -> None:
    for w in (0.0, 0.5, 1.0):
        rel = GraphRelationship(
            from_entity_id=_FROM_ID,
            to_entity_id=_TO_ID,
            edge_type=EdgeType.DEPLOYED_BY,
            source_id=_SOURCE_ID,
            chunk_id=_CHUNK_ID,
            weight=w,
            created_at=_NOW,
            updated_at=_NOW,
            ttl_expires_at=_NOW + timedelta(days=30),
        )
        assert rel.weight == w
