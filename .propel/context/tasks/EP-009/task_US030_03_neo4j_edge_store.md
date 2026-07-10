# TASK-US030-03 — `Neo4jEdgeStore`: MERGE Relationships, Stale Expiry, and Tombstone Deletion

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US030-03 |
| User Story | US-030 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `Neo4jEdgeStore` — the Neo4j write component for graph relationships. Provides `merge_relationships()` (AC-2), `delete_entity_relationships()` (AC-3 tombstone), and `expire_stale_relationships()` (AC-5 TTL expiry). Reuses `Neo4jSettings` from TASK-US028-03 to avoid config duplication.

## Implementation Details

**Technology:** Python 3.11+, `neo4j[asyncio]>=5.0`, Pydantic v2

**File locations:**
- `src/knowledge_graph/stores/neo4j_edge_store.py` — `Neo4jEdgeStore`
- `tests/knowledge_graph/test_neo4j_edge_store.py`

---

### `Neo4jEdgeStore`

```python
# src/knowledge_graph/stores/neo4j_edge_store.py
from __future__ import annotations
import logging
from datetime                            import datetime, timezone
from neo4j                               import AsyncGraphDatabase, AsyncDriver
from src.knowledge_graph.stores.neo4j_store   import Neo4jSettings
from src.knowledge_graph.schemas.relationship import GraphRelationship
from src.knowledge_graph.schemas.edge         import EdgeType

logger = logging.getLogger(__name__)

# Map EdgeType to its Cypher relationship type string.
_EDGE_CYPHER: dict[EdgeType, str] = {
    EdgeType.DEPENDS_ON:   "DEPENDS_ON",
    EdgeType.OWNED_BY:     "OWNED_BY",
    EdgeType.HAS_INCIDENT: "HAS_INCIDENT",
    EdgeType.DEPLOYED_BY:  "DEPLOYED_BY",
    EdgeType.REFERENCES:   "REFERENCES",
}


class Neo4jEdgeStore:
    def __init__(self, settings: Neo4jSettings | None = None) -> None:
        self._settings = settings or Neo4jSettings()
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            self._settings.uri,
            auth=(self._settings.username, self._settings.password),
        )

    async def merge_relationships(self, relationships: list[GraphRelationship]) -> int:
        """
        Upsert all relationships into Neo4j using MERGE on (from_id, to_id, edge_type).

        For each EdgeType present in the batch, runs one UNWIND query to MERGE
        all relationships of that type in a single round-trip.

        ON CREATE: sets all properties including created_at.
        ON MATCH : updates weight, updated_at, ttl_expires_at, chunk_id, source_id.
                   Does NOT overwrite created_at on existing edges.

        Dynamic label safety: edge type strings come exclusively from the
        _EDGE_CYPHER dict (closed, bounded by the EdgeType enum) and are never
        derived from user input.

        Returns number of relationships processed.
        """
        if not relationships:
            return 0

        # Group by edge type so each UNWIND targets a single relationship label.
        by_type: dict[str, list[dict]] = {}
        for rel in relationships:
            label = _EDGE_CYPHER[rel.edge_type]
            props = {
                "from_id":       rel.from_entity_id,
                "to_id":         rel.to_entity_id,
                "source_id":     str(rel.source_id),
                "chunk_id":      str(rel.chunk_id),
                "weight":        rel.weight,
                "created_at":    rel.created_at.isoformat(),
                "updated_at":    rel.updated_at.isoformat(),
                "ttl_expires_at": rel.ttl_expires_at.isoformat(),
            }
            by_type.setdefault(label, []).append(props)

        async with self._driver.session(database=self._settings.database) as session:
            for label, batch in by_type.items():
                for i in range(0, len(batch), self._settings.batch_size):
                    sub = batch[i : i + self._settings.batch_size]
                    await session.run(
                        f"""
                        UNWIND $batch AS props
                        MATCH (a {{entity_id: props.from_id}})
                        MATCH (b {{entity_id: props.to_id}})
                        MERGE (a)-[r:{label}]->(b)
                        ON CREATE SET
                            r.source_id      = props.source_id,
                            r.chunk_id       = props.chunk_id,
                            r.weight         = props.weight,
                            r.created_at     = props.created_at,
                            r.updated_at     = props.updated_at,
                            r.ttl_expires_at = props.ttl_expires_at
                        ON MATCH SET
                            r.source_id      = props.source_id,
                            r.chunk_id       = props.chunk_id,
                            r.weight         = props.weight,
                            r.updated_at     = props.updated_at,
                            r.ttl_expires_at = props.ttl_expires_at
                        """,
                        batch=sub,
                    )
        logger.debug(
            "Neo4jEdgeStore: merged %d relationships across %d edge types",
            len(relationships), len(by_type),
        )
        return len(relationships)

    async def delete_entity_relationships(self, entity_id: str) -> int:
        """
        Tombstone pattern (AC-3): delete ALL relationships incident on the given
        entity (both incoming and outgoing) when the entity is deleted from the source.

        Returns the number of deleted relationships.
        """
        result = await self._run_write(
            """
            MATCH (n {entity_id: $entity_id})-[r]-()
            WITH r, count(r) AS total
            DELETE r
            RETURN total
            """,
            entity_id=entity_id,
        )
        count = result[0]["total"] if result else 0
        logger.info(
            "Neo4jEdgeStore: tombstone deleted %d relationships for entity=%s",
            count, entity_id,
        )
        return count

    async def expire_stale_relationships(self, cutoff: datetime) -> int:
        """
        AC-5: remove relationships whose ttl_expires_at is earlier than `cutoff`.

        Runs in batches of 10 000 to avoid long-running transactions on large graphs.
        Returns total number of expired relationships.
        """
        total_deleted = 0
        batch_size    = 10_000

        while True:
            result = await self._run_write(
                """
                MATCH ()-[r]->()
                WHERE r.ttl_expires_at < $cutoff
                WITH r LIMIT $batch_size
                DELETE r
                RETURN count(r) AS deleted
                """,
                cutoff     = cutoff.isoformat(),
                batch_size = batch_size,
            )
            deleted = result[0]["deleted"] if result else 0
            total_deleted += deleted
            if deleted < batch_size:
                break   # no more stale relationships

        if total_deleted:
            logger.info(
                "Neo4jEdgeStore: expired %d stale relationships (cutoff=%s)",
                total_deleted, cutoff.isoformat(),
            )
        return total_deleted

    async def close(self) -> None:
        await self._driver.close()

    # ------------------------------------------------------------------ #
    # Private helper                                                       #
    # ------------------------------------------------------------------ #

    async def _run_write(self, query: str, **params) -> list[dict]:
        async with self._driver.session(database=self._settings.database) as session:
            result = await session.run(query.strip(), **params)
            return [dict(record) async for record in result]
```

**Relationship MERGE key:**

`MERGE (a)-[r:{label}]->(b)` matches on the triple `(from_entity_id, to_entity_id, edge_type)`. If the same two entities appear in multiple chunks with the same relationship type, `ON MATCH` updates `updated_at` and `ttl_expires_at` — resetting the TTL clock. This is the intended behaviour: frequently co-occurring relationships remain in the graph; infrequent ones expire after 30 days (AC-5).

**MATCH before MERGE:**

The Cypher pattern `MATCH (a {entity_id: ...}) MATCH (b {entity_id: ...}) MERGE (a)-[r]->(b)` is correct: if either endpoint node does not exist, the `MATCH` clause returns no rows and the `MERGE` is never executed — no dangling relationships are created. Endpoint nodes are guaranteed to exist because `Neo4jEntityStore.merge_entities()` (TASK-US028-03) runs before `Neo4jEdgeStore.merge_relationships()` in the `GraphUpdaterConsumer` pipeline.

**Stale expiry batching (AC-5):**

Running `DELETE r` without `LIMIT` on a large graph creates a transaction with millions of deleted rows, which can cause Neo4j heap pressure. The 10,000-row batch loop keeps each transaction small and lets Neo4j GC between iterations.

**Dynamic label safety:**

The `label` variable in each Cypher string comes exclusively from `_EDGE_CYPHER[rel.edge_type]`, which is keyed by `EdgeType` enum values. There is no user-supplied string in the query template. The set of valid relationship labels is closed and bounded by the enum.

## Acceptance Criteria

- [ ] `merge_relationships([])` returns `0` without opening a Neo4j session
- [ ] `merge_relationships()` groups edges by type and executes one `UNWIND` per type per batch
- [ ] `delete_entity_relationships()` deletes both incoming and outgoing relationships for the entity
- [ ] `expire_stale_relationships(cutoff)` loops until fewer than 10 000 rows are returned per iteration
- [ ] Cypher strings contain no user-supplied interpolation — only `$`-parameterised values and `_EDGE_CYPHER` enum literals
- [ ] `ON MATCH` does NOT overwrite `created_at` on existing relationships
- [ ] `mypy --strict` passes

## Dependencies

- TASK-US028-03 (`Neo4jSettings` — reused from `src/knowledge_graph/stores/neo4j_store.py`)
- TASK-US030-01 (`GraphRelationship`, `EdgeType`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `AsyncDriver` and `AsyncSession` via `AsyncMock`; no live Neo4j in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
