# TASK-US028-03 — `Neo4jEntityStore`: `MERGE` Upsert and Deduplication

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US028-03 |
| User Story | US-028 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `Neo4jEntityStore` — the component that writes `ExtractedEntity` objects to Neo4j as typed nodes using `MERGE` on `entity_id`. Satisfies AC-3 (required node properties: `entity_id`, `type`, `name`, `source_id`, `created_at`) and AC-4 (deduplication: two extractions of the same entity result in exactly one node). Lays the Neo4j schema foundation required by US-029 (`DEPENDS_ON`, `OWNED_BY`, etc. edge traversal).

## Implementation Details

**Technology:** Python 3.11+, `neo4j[asyncio]>=5.0`, Pydantic v2, `pydantic-settings`

**File locations:**
- `src/knowledge_graph/stores/neo4j_store.py` — `Neo4jEntityStore`, `Neo4jSettings`
- `src/knowledge_graph/stores/constraints.py` — Cypher constraint setup script
- `tests/knowledge_graph/test_neo4j_entity_store.py`

---

### `Neo4jSettings`

```python
# src/knowledge_graph/stores/neo4j_store.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Neo4jSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEO4J_", env_file=".env")

    uri:      str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"
    # Max entities per UNWIND batch; reduces round-trips for bulk extraction results.
    batch_size: int = 100
```

---

### Neo4j schema constraints

Constraints must be created once at startup (idempotent). Each `EntityType` gets its own label, enabling label-specific indexes for US-029 traversal performance.

```python
# src/knowledge_graph/stores/constraints.py
ENTITY_TYPES = [
    "Service", "Repository", "Developer",
    "Incident", "Deployment", "AlertRule", "Document",
]

# Called once during application lifespan startup.
CONSTRAINT_STATEMENTS = [
    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{entity_type}) "
    f"REQUIRE n.entity_id IS UNIQUE"
    for entity_type in ENTITY_TYPES
]
```

---

### `Neo4jEntityStore`

```python
# src/knowledge_graph/stores/neo4j_store.py (continued)
import logging
from datetime                      import datetime, timezone
from neo4j                         import AsyncGraphDatabase, AsyncDriver
from src.knowledge_graph.schemas.entity import ExtractedEntity
from src.knowledge_graph.stores.constraints import CONSTRAINT_STATEMENTS

logger = logging.getLogger(__name__)


class Neo4jEntityStore:
    def __init__(self, settings: Neo4jSettings | None = None) -> None:
        self._settings = settings or Neo4jSettings()
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            self._settings.uri,
            auth=(self._settings.username, self._settings.password),
        )

    async def apply_constraints(self) -> None:
        """
        Idempotent: run once at lifespan startup to ensure uniqueness constraints exist.
        Uses IF NOT EXISTS so it is safe to call on every application start.
        """
        async with self._driver.session(database=self._settings.database) as session:
            for stmt in CONSTRAINT_STATEMENTS:
                await session.run(stmt)

    async def merge_entities(self, entities: list[ExtractedEntity]) -> None:
        """
        Write all entities to Neo4j using MERGE on entity_id.

        Cypher pattern (per entity_type label):
          UNWIND $batch AS props
          MERGE (n:<Label> {entity_id: props.entity_id})
          ON CREATE SET n = props, n.created_at = props.created_at
          ON MATCH  SET n.name      = props.name,
                        n.source_id = props.source_id,
                        n.updated_at = props.updated_at

        Sending all entities for a single chunk in one UNWIND batch minimises
        round-trips while keeping Cypher type-safe per node label.
        """
        if not entities:
            return

        now = datetime.now(tz=timezone.utc).isoformat()

        # Group by entity_type so each UNWIND targets a single node label.
        by_type: dict[str, list[dict]] = {}
        for e in entities:
            props = {
                "entity_id":   e.entity_id,
                "type":        e.entity_type.value,
                "name":        e.name,
                "source_id":   str(e.source_id),
                "created_at":  e.created_at.isoformat(),
                "updated_at":  now,
                **e.properties,
            }
            by_type.setdefault(e.entity_type.value, []).append(props)

        async with self._driver.session(database=self._settings.database) as session:
            for label, batch in by_type.items():
                # Process in sub-batches to avoid overly large UNWIND payloads.
                for i in range(0, len(batch), self._settings.batch_size):
                    sub = batch[i : i + self._settings.batch_size]
                    await session.run(
                        f"""
                        UNWIND $batch AS props
                        MERGE (n:{label} {{entity_id: props.entity_id}})
                        ON CREATE SET n  = props,
                                      n.created_at = props.created_at
                        ON MATCH  SET n.name       = props.name,
                                      n.source_id  = props.source_id,
                                      n.updated_at = props.updated_at
                        """,
                        batch=sub,
                    )
            logger.debug(
                "Neo4jEntityStore: merged %d entities across %d labels",
                len(entities), len(by_type),
            )

    async def close(self) -> None:
        await self._driver.close()
```

**Deduplication guarantee (AC-4):**

`MERGE (n:{label} {entity_id: props.entity_id})` matches on the uniqueness-constrained `entity_id` property. If a node with that `entity_id` already exists (same `entity_type + canonical_name` seen in a previous chunk), `ON MATCH` updates mutable fields (`name`, `source_id`, `updated_at`) without creating a duplicate node. The uniqueness constraint (created by `apply_constraints()`) enforces this at the DB level even under concurrent writers.

**Dynamic label safety:**

The `label` variable in the Cypher string comes exclusively from `EntityType` enum values (`"Service"`, `"Repository"`, etc.), never from user-supplied input. There is no injection risk; the set of valid labels is closed and compile-time-bounded.

**Lifespan integration:**

```python
# src/gateway/lifespan.py — extend startup block
neo4j_store = Neo4jEntityStore()
await neo4j_store.apply_constraints()
app.state.neo4j_store = neo4j_store

# Shutdown
await app.state.neo4j_store.close()
```

## Acceptance Criteria

- [ ] `merge_entities()` with duplicate `entity_id` across two calls produces exactly one node (verified by Cypher `MATCH (n) WHERE n.entity_id = $id RETURN count(n)`)
- [ ] `merge_entities([])` returns immediately without opening a Neo4j session
- [ ] `apply_constraints()` called twice does not raise (idempotent via `IF NOT EXISTS`)
- [ ] All 7 entity type labels receive their own uniqueness constraint
- [ ] `updated_at` is set on `ON MATCH`; `created_at` is set only on `ON CREATE`
- [ ] Node properties include all required fields: `entity_id`, `type`, `name`, `source_id`, `created_at`
- [ ] Dynamic Cypher label comes only from `EntityType` enum values — never from user input

## Dependencies

- TASK-US028-01 (`EntityType`, `ExtractedEntity`, `make_entity_id`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `AsyncDriver` and `AsyncSession` via `AsyncMock`; no live Neo4j in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
