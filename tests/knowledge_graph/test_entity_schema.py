"""Tests for entity schemas — TASK-US028-01.

Covers all acceptance criteria:
  AC-1  make_entity_id normalises whitespace (trimmed == padded variant).
  AC-2  make_entity_id includes type prefix (Service != Repository for same name).
  AC-3  ExtractedEntity with mismatched entity_id raises ValidationError.
  AC-4  All 7 EntityType values exist.
  AC-5  All 5 EdgeType values exist.
  AC-6  ChunkIndexedEvent and EntityExtractionFailedEvent are frozen.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.knowledge_graph.schemas.edge import EdgeType, ExtractedEdge
from src.knowledge_graph.schemas.entity import (
    EntityExtractionResult,
    EntityType,
    ExtractedEntity,
    make_entity_id,
)
from src.knowledge_graph.schemas.events import (
    ChunkIndexedEvent,
    EntityExtractionFailedEvent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_CHUNK_ID = UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")
_NOW = datetime.now(tz=UTC)


def _valid_entity(**overrides: object) -> dict:
    canonical = overrides.pop("canonical_name", "auth service")
    entity_type = overrides.pop("entity_type", EntityType.SERVICE)
    return {
        "entity_id": make_entity_id(entity_type, canonical),
        "entity_type": entity_type,
        "name": "Auth Service",
        "canonical_name": canonical,
        "source_id": _SOURCE_ID,
        "chunk_id": _CHUNK_ID,
        "created_at": _NOW,
        **overrides,
    }


# ---------------------------------------------------------------------------
# AC-1 — make_entity_id normalises whitespace
# ---------------------------------------------------------------------------


def test_make_entity_id_normalises_surrounding_whitespace() -> None:
    assert make_entity_id(EntityType.SERVICE, "  Auth Service  ") == make_entity_id(
        EntityType.SERVICE, "auth service"
    )


def test_make_entity_id_normalises_mixed_case() -> None:
    assert make_entity_id(EntityType.SERVICE, "AUTH SERVICE") == make_entity_id(
        EntityType.SERVICE, "auth service"
    )


# ---------------------------------------------------------------------------
# AC-2 — make_entity_id includes type prefix
# ---------------------------------------------------------------------------


def test_make_entity_id_differs_across_types() -> None:
    assert make_entity_id(EntityType.SERVICE, "auth service") != make_entity_id(
        EntityType.REPOSITORY, "auth service"
    )


def test_make_entity_id_returns_16_hex_chars() -> None:
    result = make_entity_id(EntityType.SERVICE, "auth service")
    assert len(result) == 16
    assert all(c in "0123456789abcdef" for c in result)


# ---------------------------------------------------------------------------
# AC-3 — ExtractedEntity rejects mismatched entity_id
# ---------------------------------------------------------------------------


def test_extracted_entity_valid_construction() -> None:
    entity = ExtractedEntity(**_valid_entity())
    assert entity.entity_id == make_entity_id(EntityType.SERVICE, "auth service")


def test_extracted_entity_mismatched_entity_id_raises() -> None:
    data = _valid_entity()
    data["entity_id"] = "a" * 16  # wrong but correct length
    with pytest.raises(ValidationError, match="entity_id mismatch"):
        ExtractedEntity(**data)


def test_extracted_entity_is_immutable() -> None:
    entity = ExtractedEntity(**_valid_entity())
    with pytest.raises(ValidationError):
        entity.name = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC-4 — All 7 EntityType values
# ---------------------------------------------------------------------------


def test_entity_type_has_all_seven_values() -> None:
    expected = {"Service", "Repository", "Developer", "Incident", "Deployment", "AlertRule", "Document"}
    assert {e.value for e in EntityType} == expected


# ---------------------------------------------------------------------------
# AC-5 — All 5 EdgeType values
# ---------------------------------------------------------------------------


def test_edge_type_has_all_five_values() -> None:
    expected = {"DEPENDS_ON", "OWNED_BY", "HAS_INCIDENT", "DEPLOYED_BY", "REFERENCES"}
    assert {e.value for e in EdgeType} == expected


# ---------------------------------------------------------------------------
# AC-6 — Frozen event models
# ---------------------------------------------------------------------------


def test_chunk_indexed_event_is_frozen() -> None:
    event = ChunkIndexedEvent(
        chunk_id=_CHUNK_ID,
        source_id=_SOURCE_ID,
        tenant_id="acme",
        document_id="doc-1",
        text="hello world",
        token_count=2,
        embedding_model="text-embedding-3-small",
        indexed_at=_NOW,
    )
    with pytest.raises((ValidationError, TypeError)):
        event.tenant_id = "other"  # type: ignore[misc]


def test_entity_extraction_failed_event_is_frozen() -> None:
    event = EntityExtractionFailedEvent(
        chunk_id=_CHUNK_ID,
        source_id=_SOURCE_ID,
        tenant_id="acme",
        error="timeout",
        failed_at=_NOW,
        attempt=3,
    )
    with pytest.raises((ValidationError, TypeError)):
        event.attempt = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Additional — ExtractedEdge and EntityExtractionResult
# ---------------------------------------------------------------------------


def test_extracted_edge_valid_construction() -> None:
    from_id = make_entity_id(EntityType.SERVICE, "auth service")
    to_id = make_entity_id(EntityType.REPOSITORY, "auth-repo")
    edge = ExtractedEdge(
        from_entity_id=from_id,
        to_entity_id=to_id,
        edge_type=EdgeType.DEPENDS_ON,
    )
    assert edge.weight == 1.0


def test_extracted_edge_weight_out_of_range_raises() -> None:
    from_id = make_entity_id(EntityType.SERVICE, "auth service")
    to_id = make_entity_id(EntityType.REPOSITORY, "auth-repo")
    with pytest.raises(ValidationError):
        ExtractedEdge(
            from_entity_id=from_id,
            to_entity_id=to_id,
            edge_type=EdgeType.DEPENDS_ON,
            weight=1.5,
        )


def test_entity_extraction_result_aggregates_entities() -> None:
    entity = ExtractedEntity(**_valid_entity())
    result = EntityExtractionResult(
        chunk_id=_CHUNK_ID,
        source_id=_SOURCE_ID,
        entities=[entity],
        duration_ms=42.0,
    )
    assert len(result.entities) == 1
    assert result.duration_ms == 42.0
