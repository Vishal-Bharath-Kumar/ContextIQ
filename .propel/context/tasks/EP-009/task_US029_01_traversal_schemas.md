# TASK-US029-01 — Traversal Schemas, `TraversalConfig`, and Cypher Query Builder

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US029-01 |
| User Story | US-029 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the Pydantic schemas used across the Knowledge Graph traversal pipeline: `TraversalConfig` (depth, edge filter, budget), `GraphContextItem` (a single graph-expanded context result), and `GraphTraversalResult` (wrapper for a full traversal response). Implement `CypherQueryBuilder` — the component that produces safe, parameterised Cypher for variable-depth multi-edge traversal. Satisfies the data-contract foundation for AC-1 through AC-6.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, `pydantic-settings`

**File locations:**
- `src/knowledge_graph/traversal/schemas.py` — `TraversalConfig`, `GraphContextItem`, `GraphTraversalResult`
- `src/knowledge_graph/traversal/query_builder.py` — `CypherQueryBuilder`
- `tests/knowledge_graph/test_cypher_query_builder.py`

---

### `TraversalConfig`

```python
# src/knowledge_graph/traversal/schemas.py
from __future__ import annotations
from pydantic              import BaseModel, ConfigDict, Field
from pydantic_settings     import BaseSettings, SettingsConfigDict
from src.knowledge_graph.schemas.edge import EdgeType

class TraversalSettings(BaseSettings):
    """Runtime-configurable traversal defaults (AIR-021)."""
    model_config = SettingsConfigDict(env_prefix="KG_TRAVERSAL_", env_file=".env")

    # Default hop depth (AC-3).
    max_depth:          int   = 3
    # Maximum nodes returned per seed entity; caps result set size.
    max_nodes_per_seed: int   = 50
    # Fraction of remaining token budget that graph context may consume (AC-6).
    budget_fraction:    float = Field(default=0.25, ge=0.0, le=1.0)
    # Hard timeout for the Neo4j query call in seconds (AC-5).
    query_timeout_s:    float = 0.5


class TraversalConfig(BaseModel):
    """Per-invocation traversal parameters, derived from TraversalSettings + caller overrides."""
    model_config = ConfigDict(frozen=True)

    seed_entity_ids:    list[str] = Field(min_length=1)
    edge_types:         list[EdgeType] = Field(
        default_factory=lambda: list(EdgeType),
        description="Edge relationship types to follow. Default: all 5 types.",
    )
    max_depth:          int   = Field(default=3, ge=1, le=5)
    max_nodes_per_seed: int   = Field(default=50, ge=1, le=500)
    token_budget:       int   = Field(
        description="Maximum tokens the graph results may consume (from execution plan).",
        ge=0,
    )
```

---

### `GraphContextItem` and `GraphTraversalResult`

```python
# src/knowledge_graph/traversal/schemas.py (continued)
from datetime import datetime
from uuid     import UUID

class GraphContextItem(BaseModel):
    """Single entity returned by a graph traversal, formatted as a ranked-context entry."""
    model_config = ConfigDict(frozen=True)

    entity_id:    str
    entity_type:  str
    name:         str
    hops:         int   = Field(description="Distance in hops from the seed entity.", ge=1)
    # Abbreviated path description, e.g. "auth-service -[DEPENDS_ON]-> user-repo"
    path_summary: str
    # Free-form properties from the Neo4j node.
    properties:   dict  = Field(default_factory=dict)
    # Approximate token count for this item (used for budget enforcement).
    token_count:  int   = Field(ge=1)
    # Stable label required by AC-4.
    source:       str   = "knowledge_graph"


class GraphTraversalResult(BaseModel):
    """Output of a complete traversal for one or more seed entities."""
    model_config = ConfigDict(frozen=True)

    items:             list[GraphContextItem]
    total_tokens:      int
    query_duration_ms: float
    seeds_used:        list[str]
    truncated:         bool = Field(
        default=False,
        description="True if results were trimmed to fit within token_budget.",
    )
```

---

### `CypherQueryBuilder`

**Depth parameterisation note:** Standard Cypher variable-length path syntax (`[*1..N]`) does not accept a bound parameter for `N` — only literal integers are allowed. Because `max_depth` comes exclusively from `TraversalConfig` (validated as `int`, `ge=1`, `le=5`), it is safe to format it as an integer literal in the query string. There is no user-supplied string interpolation.

```python
# src/knowledge_graph/traversal/query_builder.py
from src.knowledge_graph.traversal.schemas import TraversalConfig
from src.knowledge_graph.schemas.edge      import EdgeType

# Map EdgeType to the Cypher relationship type string used in the graph.
_EDGE_CYPHER: dict[EdgeType, str] = {
    EdgeType.DEPENDS_ON:   "DEPENDS_ON",
    EdgeType.OWNED_BY:     "OWNED_BY",
    EdgeType.HAS_INCIDENT: "HAS_INCIDENT",
    EdgeType.DEPLOYED_BY:  "DEPLOYED_BY",
    EdgeType.REFERENCES:   "REFERENCES",
}


class CypherQueryBuilder:
    """
    Builds parameterised Cypher traversal queries.

    All external inputs (seed IDs, edge type strings) are passed as
    Cypher parameters ($seed_ids, $edge_types) — never interpolated into
    the query string — preventing Cypher injection.

    max_depth is formatted as an integer literal (never a string); it is
    validated at the Pydantic layer to be in [1, 5] before reaching this class.
    """

    def build_traversal(self, config: TraversalConfig) -> tuple[str, dict]:
        """
        Returns (cypher_query, parameters) ready for driver.session.run().

        Query shape:
          MATCH (seed:Entity)
          WHERE seed.entity_id IN $seed_ids
          MATCH path = (seed)-[r*1..<depth>]->(neighbour)
          WHERE type(r[-1]) IN $edge_types
          WITH seed, neighbour, r,
               length(path) AS hops,
               [rel IN relationships(path) | type(rel)] AS rel_types
          RETURN DISTINCT
            neighbour.entity_id      AS entity_id,
            labels(neighbour)[0]     AS entity_type,
            neighbour.name           AS name,
            hops,
            seed.name + ' -[' + type(r[-1]) + ']-> ' + neighbour.name AS path_summary,
            properties(neighbour)    AS properties
          ORDER BY hops ASC
          LIMIT $limit
        """
        depth     = config.max_depth                          # validated int, safe to format
        limit     = config.max_nodes_per_seed * len(config.seed_entity_ids)
        edge_strs = [_EDGE_CYPHER[e] for e in config.edge_types]

        query = f"""
MATCH (seed)
WHERE seed.entity_id IN $seed_ids
MATCH path = (seed)-[r*1..{depth}]->(neighbour)
WHERE ALL(rel IN relationships(path) WHERE type(rel) IN $edge_types)
  AND neighbour.entity_id <> seed.entity_id
WITH seed, neighbour,
     length(path)                                   AS hops,
     relationships(path)[-1]                        AS last_rel,
     [rel IN relationships(path) | type(rel)]       AS rel_chain
RETURN DISTINCT
    neighbour.entity_id                             AS entity_id,
    labels(neighbour)[0]                            AS entity_type,
    neighbour.name                                  AS name,
    hops,
    seed.name + ' -[' + type(last_rel) + ']-> ' + neighbour.name AS path_summary,
    properties(neighbour)                           AS properties
ORDER BY hops ASC
LIMIT $limit
"""
        params = {
            "seed_ids":   config.seed_entity_ids,
            "edge_types": edge_strs,
            "limit":      limit,
        }
        return query.strip(), params

    def build_entity_lookup(self, entity_ids: list[str]) -> tuple[str, dict]:
        """Fetch full node data for a list of known entity_ids (used by EntityLinker)."""
        query = """
MATCH (n)
WHERE n.entity_id IN $entity_ids
RETURN n.entity_id AS entity_id, labels(n)[0] AS entity_type,
       n.name AS name, properties(n) AS properties
"""
        return query.strip(), {"entity_ids": entity_ids}
```

**Token count estimation:**

A `GraphContextItem.token_count` is estimated as `ceil(len(f"{name} {path_summary} {properties}") / 4)` — the standard 4-chars-per-token heuristic used throughout the codebase. The caller enforces the budget by summing `token_count` across `GraphContextItem` list and truncating when `total_tokens >= token_budget`.

## Acceptance Criteria

- [ ] `CypherQueryBuilder.build_traversal()` produces a query with `*1..3` for `max_depth=3`
- [ ] `CypherQueryBuilder.build_traversal()` produces a query with `*1..5` for `max_depth=5`
- [ ] All external inputs (`seed_ids`, `edge_types`, `limit`) are in the `params` dict — never interpolated into the query string
- [ ] `TraversalConfig` with `seed_entity_ids=[]` raises `ValidationError` (`min_length=1`)
- [ ] `GraphContextItem.source` is always `"knowledge_graph"` (required by AC-4)
- [ ] `mypy --strict` passes

## Dependencies

- TASK-US028-01 (`EdgeType` enum from `src/knowledge_graph/schemas/edge.py`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
