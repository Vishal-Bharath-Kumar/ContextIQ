"""Pydantic v2 schemas for extracted edges — TASK-US028-01.

Defines EdgeType and ExtractedEdge, consumed by US-029 (relationship extraction).
These are defined alongside entity schemas so the Neo4j schema is consistent
from day one.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EdgeType(StrEnum):
    DEPENDS_ON = "DEPENDS_ON"
    OWNED_BY = "OWNED_BY"
    HAS_INCIDENT = "HAS_INCIDENT"
    DEPLOYED_BY = "DEPLOYED_BY"
    REFERENCES = "REFERENCES"


class ExtractedEdge(BaseModel):
    """Directed relationship between two entities."""

    model_config = ConfigDict(frozen=True)

    from_entity_id: str = Field(min_length=16, max_length=16)
    to_entity_id: str = Field(min_length=16, max_length=16)
    edge_type: EdgeType
    # Optional weight/confidence [0, 1] from the extractor.
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
