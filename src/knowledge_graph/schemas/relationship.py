"""Pydantic v2 schemas for graph relationships — TASK-US030-01.

Defines:
  RelationshipExpirySettings  — TTL configuration (AC-5), env-configurable.
  GraphRelationship           — Directed Neo4j edge with lifecycle metadata,
                                shared by EdgeInferenceEngine, Neo4jEdgeStore,
                                and GraphUpdaterConsumer.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.knowledge_graph.schemas.edge import EdgeType


class RelationshipExpirySettings(BaseSettings):
    """AC-5: stale relationship TTL, configurable via environment."""

    model_config = SettingsConfigDict(env_prefix="KG_RELATIONSHIP_", env_file=".env", extra="ignore")

    # Default TTL: 30 days. Relationships not updated within this window are expired.
    ttl_days: int = 30

    @property
    def ttl_delta(self) -> timedelta:
        return timedelta(days=self.ttl_days)


class GraphRelationship(BaseModel):
    """
    Directed relationship between two entities, ready for Neo4j MERGE.
    Carries lifecycle metadata (`updated_at`, `ttl_expires_at`) that supports
    stale-relationship expiry (AC-5) and tombstone deletion (AC-3).
    """

    model_config = ConfigDict(frozen=True)

    from_entity_id: str = Field(min_length=16, max_length=16)
    to_entity_id: str = Field(min_length=16, max_length=16)
    edge_type: EdgeType
    source_id: UUID
    chunk_id: UUID
    # Confidence score from the edge inference model [0, 1].
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime
    updated_at: datetime
    ttl_expires_at: datetime

    @model_validator(mode="after")
    def validate_no_self_loop(self) -> GraphRelationship:
        if self.from_entity_id == self.to_entity_id:
            raise ValueError(
                f"Self-loop relationship not allowed: entity_id={self.from_entity_id!r}"
            )
        return self

    @classmethod
    def create(
        cls,
        from_entity_id: str,
        to_entity_id: str,
        edge_type: EdgeType,
        source_id: UUID,
        chunk_id: UUID,
        weight: float = 1.0,
        ttl_days: int = 30,
    ) -> GraphRelationship:
        now = datetime.now(tz=UTC)
        return cls(
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            edge_type=edge_type,
            source_id=source_id,
            chunk_id=chunk_id,
            weight=weight,
            created_at=now,
            updated_at=now,
            ttl_expires_at=now + timedelta(days=ttl_days),
        )
