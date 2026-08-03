# TASK-US030-01 — Graph Relationship Schemas, `TombstoneEvent`, `GraphUpdatedEvent`, and Expiry Settings

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US030-01 |
| User Story | US-030 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the Pydantic schemas required across the incremental graph update pipeline: `GraphRelationship` (a Neo4j edge with lifecycle metadata), `TombstoneEvent` (deletion signal for AC-3), `GraphUpdatedEvent` (Kafka output for AC-6), and `RelationshipExpirySettings` (TTL configuration for AC-5). These are the data contracts shared by `EdgeInferenceEngine` (TASK-US030-02), `Neo4jEdgeStore` (TASK-US030-03), and `GraphUpdaterConsumer` (TASK-US030-04).

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, `pydantic-settings`

**File locations:**
- `src/knowledge_graph/schemas/relationship.py` — `GraphRelationship`, `RelationshipExpirySettings`
- `src/knowledge_graph/schemas/events.py` — extend existing file: `TombstoneEvent`, `GraphUpdatedEvent`
- `tests/knowledge_graph/test_relationship_schema.py`

---

### `RelationshipExpirySettings`

```python
# src/knowledge_graph/schemas/relationship.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from datetime          import timedelta

class RelationshipExpirySettings(BaseSettings):
    """AC-5: stale relationship TTL, configurable via environment."""
    model_config = SettingsConfigDict(env_prefix="KG_RELATIONSHIP_", env_file=".env")

    # Default TTL: 30 days. Relationships not updated within this window are expired.
    ttl_days: int = 30

    @property
    def ttl_delta(self) -> timedelta:
        return timedelta(days=self.ttl_days)
```

---

### `GraphRelationship`

```python
# src/knowledge_graph/schemas/relationship.py (continued)
from __future__ import annotations
from datetime   import datetime, timezone, timedelta
from uuid       import UUID
from pydantic   import BaseModel, ConfigDict, Field, model_validator
from src.knowledge_graph.schemas.edge import EdgeType

class GraphRelationship(BaseModel):
    """
    Directed relationship between two entities, ready for Neo4j MERGE.
    Carries lifecycle metadata (`updated_at`, `ttl_expires_at`) that supports
    stale-relationship expiry (AC-5) and tombstone deletion (AC-3).
    """
    model_config = ConfigDict(frozen=True)

    from_entity_id:  str       = Field(min_length=16, max_length=16)
    to_entity_id:    str       = Field(min_length=16, max_length=16)
    edge_type:       EdgeType
    source_id:       UUID
    chunk_id:        UUID
    # Confidence score from the edge inference model [0, 1].
    weight:          float     = Field(default=1.0, ge=0.0, le=1.0)
    created_at:      datetime
    updated_at:      datetime
    ttl_expires_at:  datetime

    @model_validator(mode="after")
    def validate_no_self_loop(self) -> "GraphRelationship":
        if self.from_entity_id == self.to_entity_id:
            raise ValueError(
                f"Self-loop relationship not allowed: entity_id={self.from_entity_id!r}"
            )
        return self

    @classmethod
    def create(
        cls,
        from_entity_id: str,
        to_entity_id:   str,
        edge_type:      EdgeType,
        source_id:      UUID,
        chunk_id:       UUID,
        weight:         float = 1.0,
        ttl_days:       int   = 30,
    ) -> "GraphRelationship":
        now = datetime.now(tz=timezone.utc)
        return cls(
            from_entity_id = from_entity_id,
            to_entity_id   = to_entity_id,
            edge_type      = edge_type,
            source_id      = source_id,
            chunk_id       = chunk_id,
            weight         = weight,
            created_at     = now,
            updated_at     = now,
            ttl_expires_at = now + timedelta(days=ttl_days),
        )
```

---

### Kafka event schemas (extend existing `events.py`)

```python
# src/knowledge_graph/schemas/events.py  — extend existing file (do NOT replace)
# Append after existing ChunkIndexedEvent / EntityExtractionFailedEvent definitions.

class TombstoneEvent(BaseModel):
    """
    Deletion signal consumed by GraphUpdaterConsumer to remove relationships
    for a deleted entity (AC-3 tombstone pattern).
    Emitted by the connector sync pipeline when a document is removed.
    """
    model_config = ConfigDict(frozen=True)

    event_type:  str  = "knowledge_entity_tombstone"
    entity_id:   str  = Field(min_length=16, max_length=16)
    source_id:   UUID
    tenant_id:   str
    document_id: str
    deleted_at:  datetime


class GraphUpdatedEvent(BaseModel):
    """
    Emitted to `knowledge.graph.updated` after each incremental update batch (AC-6).
    Downstream consumers (e.g. traversal cache invalidation) subscribe to this topic.
    """
    model_config = ConfigDict(frozen=True)

    event_type:             str   = "knowledge_graph_updated"
    source_id:              UUID
    tenant_id:              str
    chunks_processed:       int
    entities_upserted:      int
    relationships_upserted: int
    relationships_expired:  int
    updated_at:             datetime
```

---

### Kafka topic registry

| Topic | Producer | Consumer |
|---|---|---|
| `knowledge.source.synced` | `SyncJobExecutor` (US-026) | `GraphUpdaterConsumer` |
| `knowledge.chunk.indexed` | `IndexingPipeline` (US-027) | `EntityConsumer` (US-028), `GraphUpdaterConsumer` |
| `knowledge.entity.tombstone` | connector sync pipeline | `GraphUpdaterConsumer` |
| `knowledge.graph.updated` | `GraphUpdaterConsumer` | downstream (traversal cache, etc.) |

## Acceptance Criteria

- [ ] `GraphRelationship` with `from_entity_id == to_entity_id` raises `ValidationError` (no self-loops)
- [ ] `GraphRelationship.create()` sets `ttl_expires_at = created_at + timedelta(days=ttl_days)`
- [ ] `RelationshipExpirySettings(ttl_days=7).ttl_delta == timedelta(days=7)`
- [ ] All four new Kafka event types have `ConfigDict(frozen=True)`
- [ ] `GraphUpdatedEvent.event_type` defaults to `"knowledge_graph_updated"`
- [ ] `mypy --strict` passes

## Dependencies

- TASK-US028-01 (`EdgeType` enum from `src/knowledge_graph/schemas/edge.py`)
- TASK-US028-01 (`ChunkIndexedEvent`, existing `events.py` — this task extends it)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
