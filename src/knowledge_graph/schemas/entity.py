"""Pydantic v2 schemas for extracted entities — TASK-US028-01.

Defines EntityType, make_entity_id, ExtractedEntity, and EntityExtractionResult.
These form the data contract shared by EntityExtractor (TASK-US028-02),
Neo4jEntityStore (TASK-US028-03), and the Kafka consumer (TASK-US028-04).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EntityType(StrEnum):
    SERVICE = "Service"
    REPOSITORY = "Repository"
    DEVELOPER = "Developer"
    INCIDENT = "Incident"
    DEPLOYMENT = "Deployment"
    ALERT_RULE = "AlertRule"
    DOCUMENT = "Document"


def make_entity_id(entity_type: EntityType, canonical_name: str) -> str:
    """Derive a deterministic, collision-resistant 16-character hex entity ID.

    Formula: SHA-256( "{entity_type}:{canonical_name_lower_stripped}" )[:16]

    Canonical name is lowercased and stripped to normalise minor formatting
    differences (e.g. "  Auth Service " == "auth service").  The type prefix
    prevents cross-type collisions for names that are identical across types.
    """
    key = f"{entity_type}:{canonical_name.strip().lower()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class ExtractedEntity(BaseModel):
    """Immutable entity extracted from a chunk by the LLM extractor."""

    model_config = ConfigDict(frozen=True)

    entity_id: str = Field(
        description="Deterministic 16-hex-char ID derived from type + canonical_name.",
        min_length=16,
        max_length=16,
    )
    entity_type: EntityType
    name: str = Field(min_length=1, max_length=512)
    canonical_name: str = Field(
        description="Normalised form of name (lowercase, stripped) used in entity_id derivation.",
        min_length=1,
        max_length=512,
    )
    source_id: UUID
    chunk_id: UUID
    created_at: datetime
    # Optional free-form properties stored on the Neo4j node alongside the required fields.
    properties: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_entity_id_matches_derivation(self) -> ExtractedEntity:
        expected = make_entity_id(self.entity_type, self.canonical_name)
        if self.entity_id != expected:
            raise ValueError(
                f"entity_id mismatch: provided={self.entity_id!r} "
                f"expected={expected!r} for type={self.entity_type} name={self.canonical_name!r}"
            )
        return self


class EntityExtractionResult(BaseModel):
    """Output of a single chunk extraction pass."""

    model_config = ConfigDict(frozen=True)

    chunk_id: UUID
    source_id: UUID
    entities: list[ExtractedEntity]
    # Wall-clock extraction time in milliseconds; used for AC-5 SLA monitoring.
    duration_ms: float
