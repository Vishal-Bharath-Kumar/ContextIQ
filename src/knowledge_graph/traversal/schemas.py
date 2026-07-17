"""Pydantic v2 schemas for the Knowledge Graph traversal pipeline — TASK-US029-01.

Defines TraversalSettings (env-configurable defaults), TraversalConfig
(per-invocation parameters), GraphContextItem (single traversal result),
and GraphTraversalResult (full traversal response wrapper).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.knowledge_graph.schemas.edge import EdgeType


class TraversalSettings(BaseSettings):
    """Runtime-configurable traversal defaults (AIR-021)."""

    model_config = SettingsConfigDict(env_prefix="KG_TRAVERSAL_", env_file=".env", extra="ignore")

    # Default hop depth (AC-3).
    max_depth: int = 3
    # Maximum nodes returned per seed entity; caps result set size.
    max_nodes_per_seed: int = 50
    # Fraction of remaining token budget that graph context may consume (AC-6).
    budget_fraction: float = Field(default=0.25, ge=0.0, le=1.0)
    # Hard timeout for the Neo4j query call in seconds (AC-5).
    query_timeout_s: float = 0.5


class TraversalConfig(BaseModel):
    """Per-invocation traversal parameters, derived from TraversalSettings + caller overrides."""

    model_config = ConfigDict(frozen=True)

    seed_entity_ids: list[str] = Field(min_length=1)
    edge_types: list[EdgeType] = Field(
        default_factory=lambda: list(EdgeType),
        description="Edge relationship types to follow. Default: all 5 types.",
    )
    max_depth: int = Field(default=3, ge=1, le=5)
    max_nodes_per_seed: int = Field(default=50, ge=1, le=500)
    token_budget: int = Field(
        description="Maximum tokens the graph results may consume (from execution plan).",
        ge=0,
    )


class GraphContextItem(BaseModel):
    """Single entity returned by a graph traversal, formatted as a ranked-context entry."""

    model_config = ConfigDict(frozen=True)

    entity_id: str
    entity_type: str
    name: str
    hops: int = Field(description="Distance in hops from the seed entity.", ge=1)
    # Abbreviated path description, e.g. "auth-service -[DEPENDS_ON]-> user-repo"
    path_summary: str
    # Free-form properties from the Neo4j node.
    properties: dict[str, object] = Field(default_factory=dict)
    # Approximate token count for this item (used for budget enforcement).
    token_count: int = Field(ge=1)
    # Stable label required by AC-4.
    source: str = "knowledge_graph"


class GraphTraversalResult(BaseModel):
    """Output of a complete traversal for one or more seed entities."""

    model_config = ConfigDict(frozen=True)

    items: list[GraphContextItem]
    total_tokens: int
    query_duration_ms: float
    seeds_used: list[str]
    truncated: bool = Field(
        default=False,
        description="True if results were trimmed to fit within token_budget.",
    )
