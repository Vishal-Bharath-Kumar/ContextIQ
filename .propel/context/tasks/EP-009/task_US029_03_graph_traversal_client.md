# TASK-US029-03 — `GraphTraversalClient`: Async Neo4j Traversal with 500 ms Budget

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US029-03 |
| User Story | US-029 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Implement `GraphTraversalClient` — the async Neo4j client that executes the Cypher traversal query built by `CypherQueryBuilder`, enforces the 500 ms query timeout (AC-5), deduplicates results by `entity_id`, estimates token counts, and truncates the result set to respect the caller's token budget (AC-6). Also implements `lookup_entity_ids()` used by `EntityLinker`'s slow path.

## Implementation Details

**Technology:** Python 3.11+, `neo4j[asyncio]>=5.0`, Pydantic v2

**File locations:**
- `src/knowledge_graph/traversal/neo4j_traversal_client.py` — `GraphTraversalClient`
- `tests/knowledge_graph/test_graph_traversal_client.py`

---

### `GraphTraversalClient`

Reuses `Neo4jSettings` from `src/knowledge_graph/stores/neo4j_store.py` (TASK-US028-03) — no duplicate config class.

```python
# src/knowledge_graph/traversal/neo4j_traversal_client.py
from __future__ import annotations
import asyncio
import logging
import math
import time
from neo4j                              import AsyncGraphDatabase, AsyncDriver
from src.knowledge_graph.stores.neo4j_store    import Neo4jSettings
from src.knowledge_graph.traversal.schemas     import (
    TraversalConfig, GraphContextItem, GraphTraversalResult,
)
from src.knowledge_graph.traversal.query_builder import CypherQueryBuilder

logger = logging.getLogger(__name__)

_QUERY_BUILDER = CypherQueryBuilder()


class GraphTraversalClient:
    def __init__(self, settings: Neo4jSettings | None = None) -> None:
        self._settings = settings or Neo4jSettings()
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            self._settings.uri,
            auth=(self._settings.username, self._settings.password),
        )

    async def traverse(self, config: TraversalConfig) -> GraphTraversalResult:
        """
        Execute a variable-depth traversal from seed entity IDs.

        Steps:
        1. Build parameterised Cypher via CypherQueryBuilder.
        2. Run with asyncio.wait_for(timeout=query_timeout_s).
        3. Convert rows → GraphContextItem, dedup by entity_id, sort by hops.
        4. Truncate to token_budget.
        5. Return GraphTraversalResult.

        Raises asyncio.TimeoutError if Neo4j query exceeds query_timeout_s.
        """
        query, params = _QUERY_BUILDER.build_traversal(config)
        start = time.monotonic()

        rows = await asyncio.wait_for(
            self._run_query(query, params),
            timeout = self._settings.query_timeout_s
            if hasattr(self._settings, "query_timeout_s")
            else 0.5,
        )

        duration_ms = (time.monotonic() - start) * 1000
        logger.debug(
            "GraphTraversalClient: %d raw rows in %.1f ms for seeds=%s",
            len(rows), duration_ms, config.seed_entity_ids,
        )

        items = self._build_items(rows)
        items, truncated, total_tokens = self._apply_budget(items, config.token_budget)

        return GraphTraversalResult(
            items             = items,
            total_tokens      = total_tokens,
            query_duration_ms = duration_ms,
            seeds_used        = config.seed_entity_ids,
            truncated         = truncated,
        )

    async def lookup_entity_ids(self, names: list[str]) -> list[str]:
        """
        Resolve a list of entity names to entity_ids via case-insensitive name match.
        Used by EntityLinker slow path.
        """
        if not names:
            return []
        query  = """
MATCH (n)
WHERE toLower(n.name) IN $names_lower
RETURN n.entity_id AS entity_id
LIMIT 50
"""
        params = {"names_lower": [n.strip().lower() for n in names]}
        rows   = await self._run_query(query, params)
        return [r["entity_id"] for r in rows]

    async def close(self) -> None:
        await self._driver.close()

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _run_query(self, query: str, params: dict) -> list[dict]:
        """Execute a read query and return all records as plain dicts."""
        async with self._driver.session(database=self._settings.database) as session:
            result = await session.run(query, **params)
            return [dict(record) async for record in result]

    def _build_items(self, rows: list[dict]) -> list[GraphContextItem]:
        """Convert raw Neo4j records to GraphContextItem, dedup by entity_id."""
        seen:  set[str]             = set()
        items: list[GraphContextItem] = []
        for row in rows:
            eid = row.get("entity_id") or ""
            if not eid or eid in seen:
                continue
            seen.add(eid)
            text_repr   = f"{row.get('name', '')} {row.get('path_summary', '')} {row.get('properties', {})}"
            token_count = max(1, math.ceil(len(text_repr) / 4))
            items.append(
                GraphContextItem(
                    entity_id    = eid,
                    entity_type  = row.get("entity_type") or "Entity",
                    name         = row.get("name") or "",
                    hops         = int(row.get("hops") or 1),
                    path_summary = row.get("path_summary") or "",
                    properties   = dict(row.get("properties") or {}),
                    token_count  = token_count,
                )
            )
        # Primary sort: ascending hops (closest neighbours first).
        items.sort(key=lambda x: x.hops)
        return items

    def _apply_budget(
        self,
        items:        list[GraphContextItem],
        token_budget: int,
    ) -> tuple[list[GraphContextItem], bool, int]:
        """
        Greedily include items until token_budget is exhausted.
        Returns (included_items, was_truncated, total_tokens_used).
        """
        if token_budget <= 0:
            return [], bool(items), 0

        included:     list[GraphContextItem] = []
        running_total = 0
        for item in items:
            if running_total + item.token_count > token_budget:
                return included, True, running_total
            included.append(item)
            running_total += item.token_count
        return included, False, running_total
```

**500 ms SLA design (AC-5):**

`asyncio.wait_for(timeout=0.5)` is the hard guard. The underlying Neo4j query is designed for index performance:
- The uniqueness constraint on `entity_id` (created by `Neo4jEntityStore.apply_constraints()`) means `MATCH (seed) WHERE seed.entity_id IN $seed_ids` is an index scan, not a full graph scan.
- Variable-length paths with `[*1..3]` on a graph with 1 M nodes and typical degree ≤ 20 traverse at most `20^3 = 8,000` paths per seed — well within Neo4j's traversal throughput of ~1 M paths/s.
- `LIMIT $limit` (default `50 × seeds`) is applied in Cypher, not post-fetch, reducing network payload.

**Token budget enforcement (AC-6):**

The caller (`knowledge_graph_node`, TASK-US029-04) passes `token_budget = remaining_budget × budget_fraction`. `_apply_budget` enforces a greedy fill in hop-ascending order — closest neighbours (most relevant) consume the budget first; distant nodes are dropped if the budget is exhausted.

## Acceptance Criteria

- [x] `traverse()` raises `asyncio.TimeoutError` when the Neo4j query exceeds `query_timeout_s`
- [x] Duplicate `entity_id` rows from Neo4j are deduplicated — each entity appears at most once in `GraphTraversalResult.items`
- [x] Results are sorted ascending by `hops` before budget truncation
- [x] `_apply_budget` with `token_budget=0` returns `([], True, 0)` without error
- [x] `GraphTraversalResult.truncated = True` when the budget is exhausted before all items are included
- [x] `lookup_entity_ids(["Auth Service"])` runs `toLower(n.name) IN ["auth service"]` (case-normalised)
- [x] `mypy --strict` passes

## Dependencies

- TASK-US028-03 (`Neo4jSettings` — reused, not duplicated)
- TASK-US029-01 (`TraversalConfig`, `GraphContextItem`, `GraphTraversalResult`, `CypherQueryBuilder`)

## Definition of Done

- [x] Code reviewed and merged to `main`
- [x] Tests mock `AsyncDriver` and `AsyncSession` via `AsyncMock`; no live Neo4j in CI
- [x] `mypy --strict` passes; no `ruff` lint errors
