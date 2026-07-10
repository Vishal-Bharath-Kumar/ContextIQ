# TASK-US029-04 — `knowledge_graph_node()` LangGraph Node and `AgentState` Extensions

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US029-04 |
| User Story | US-029 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the `knowledge_graph_node()` LangGraph node that wires `EntityLinker` → `GraphTraversalClient` → `ranked_context` append. Extend `AgentState` with graph-specific fields. Register the node in the existing `StateGraph`. Satisfies AC-1 (Cypher traversal from ranked context), AC-4 (results appended with `source: knowledge_graph`), and AC-6 (token budget guard from execution plan).

## Implementation Details

**Technology:** Python 3.11+, LangGraph `>=0.2.0`, Pydantic v2, OpenTelemetry, Langfuse `>=2.0`

**File locations:**
- `src/agents/state.py` — extend existing `AgentState` TypedDict
- `src/knowledge_graph/nodes/knowledge_graph_node.py` — `knowledge_graph_node()`
- `src/agents/graph.py` — register node in existing `StateGraph`
- `tests/knowledge_graph/test_knowledge_graph_node.py`

---

### `AgentState` extensions

```python
# src/agents/state.py  — extend existing TypedDict (do NOT replace)
from typing import TypedDict, NotRequired
from src.knowledge_graph.traversal.schemas import GraphContextItem

class AgentState(TypedDict):
    # … existing fields (query, ranked_context, execution_plan, selected_model_id, …) …

    # New fields added by knowledge_graph_node:
    graph_context_items:      NotRequired[list[GraphContextItem]]
    # True when traversal was skipped (no seeds found, zero budget, or timeout).
    graph_traversal_skipped:  NotRequired[bool]
    # Tokens consumed by graph context; used for downstream budget accounting.
    graph_tokens_used:        NotRequired[int]
```

---

### `knowledge_graph_node()`

```python
# src/knowledge_graph/nodes/knowledge_graph_node.py
from __future__ import annotations
import asyncio
import logging
from opentelemetry         import trace
from langfuse              import Langfuse

from src.agents.state      import AgentState
from src.knowledge_graph.traversal.entity_linker         import EntityLinker
from src.knowledge_graph.traversal.neo4j_traversal_client import GraphTraversalClient
from src.knowledge_graph.traversal.schemas               import TraversalConfig
from src.knowledge_graph.traversal.schemas               import TraversalSettings
from src.knowledge_graph.schemas.edge                    import EdgeType

logger  = logging.getLogger(__name__)
tracer  = trace.get_tracer(__name__)
langfuse = Langfuse()


async def knowledge_graph_node(state: AgentState) -> AgentState:
    """
    LangGraph node — Knowledge Graph context expansion.

    Execution steps:
    1. Check remaining token budget from execution_plan; skip if zero.
    2. Call EntityLinker.resolve(ranked_context) → seed entity_ids.
    3. Skip gracefully if no seeds found.
    4. Build TraversalConfig from seeds + TraversalSettings.
    5. Call GraphTraversalClient.traverse(config).
    6. Append GraphContextItem list to ranked_context with source="knowledge_graph".
    7. Update AgentState with graph_context_items, graph_tokens_used.
    """
    settings = TraversalSettings()

    ranked_context: list[dict] = state.get("ranked_context") or []
    execution_plan: dict       = state.get("execution_plan") or {}

    remaining_budget: int = execution_plan.get("remaining_tokens", 0)
    token_budget      = int(remaining_budget * settings.budget_fraction)

    with tracer.start_as_current_span("knowledge_graph.traverse") as span:
        span.set_attribute("kg.remaining_budget",  remaining_budget)
        span.set_attribute("kg.token_budget",      token_budget)

        if token_budget <= 0:
            logger.info("knowledge_graph_node: zero token budget — skipping traversal")
            span.set_attribute("kg.skipped", True)
            return {
                **state,
                "graph_traversal_skipped": True,
                "graph_tokens_used":       0,
                "graph_context_items":     [],
            }

        # Resolve seeds
        client  = GraphTraversalClient()
        linker  = EntityLinker(traversal_client=client)
        seeds   = await linker.resolve(ranked_context)

        if not seeds:
            logger.info("knowledge_graph_node: no seed entities found — skipping traversal")
            span.set_attribute("kg.skipped", True)
            return {
                **state,
                "graph_traversal_skipped": True,
                "graph_tokens_used":       0,
                "graph_context_items":     [],
            }

        span.set_attribute("kg.seed_count", len(seeds))

        # Build traversal config
        config = TraversalConfig(
            seed_entity_ids    = seeds,
            edge_types         = list(EdgeType),   # all 5 edge types (AC-2)
            max_depth          = settings.max_depth,
            max_nodes_per_seed = settings.max_nodes_per_seed,
            token_budget       = token_budget,
        )

        try:
            result = await client.traverse(config)
        except asyncio.TimeoutError:
            logger.warning(
                "knowledge_graph_node: traversal timed out for seeds=%s", seeds
            )
            span.set_attribute("kg.timeout", True)
            return {
                **state,
                "graph_traversal_skipped": True,
                "graph_tokens_used":       0,
                "graph_context_items":     [],
            }

        span.set_attribute("kg.items_returned", len(result.items))
        span.set_attribute("kg.tokens_used",    result.total_tokens)
        span.set_attribute("kg.truncated",      result.truncated)
        span.set_attribute("kg.duration_ms",    result.query_duration_ms)

        # Langfuse observation for LLM cost tracking integration
        langfuse.create_event(
            name       = "knowledge_graph_traversal",
            input      = {"seeds": seeds, "max_depth": config.max_depth},
            output     = {"items": len(result.items), "tokens": result.total_tokens},
            metadata   = {"duration_ms": result.query_duration_ms, "truncated": result.truncated},
        )

        # Append graph results to ranked_context (AC-4)
        graph_context_dicts = [item.model_dump() for item in result.items]
        updated_ranked_context = ranked_context + graph_context_dicts

        return {
            **state,
            "ranked_context":          updated_ranked_context,
            "graph_context_items":     result.items,
            "graph_traversal_skipped": False,
            "graph_tokens_used":       result.total_tokens,
        }
```

---

### `StateGraph` registration

```python
# src/agents/graph.py — extend existing StateGraph (do NOT replace)
from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

# Insert after the ranking node and before the response generation node.
# Exact position depends on the existing graph topology from US-014.
graph.add_node("knowledge_graph", knowledge_graph_node)
graph.add_edge("ranking",         "knowledge_graph")
graph.add_edge("knowledge_graph", "response_generation")
```

**Node placement rationale:**

`knowledge_graph_node` sits between the ranking node (which produces `ranked_context`) and the response generation node (which consumes it). This placement ensures:
1. Seeds are resolved from already-ranked, high-quality context — not raw retrieval results.
2. Graph-expanded items are available to the response generator within the same invocation.
3. The execution plan's `remaining_tokens` budget is already set by the ranking node.

---

### Graceful skip conditions

The node returns immediately (sets `graph_traversal_skipped=True`) in three cases, all of which preserve the existing `ranked_context` unchanged:

| Condition | Log message |
|---|---|
| `token_budget <= 0` | "zero token budget — skipping traversal" |
| No seed entities found | "no seed entities found — skipping traversal" |
| `asyncio.TimeoutError` from Neo4j | "traversal timed out for seeds=..." |

## Acceptance Criteria

- [ ] `knowledge_graph_node` appends `GraphContextItem` dicts to `ranked_context` with `source="knowledge_graph"` on success
- [ ] `graph_context_items` in returned state matches the `GraphTraversalResult.items` list
- [ ] `graph_traversal_skipped=True` when `remaining_tokens=0` (zero budget)
- [ ] `graph_traversal_skipped=True` when `EntityLinker.resolve()` returns `[]`
- [ ] `graph_traversal_skipped=True` when `GraphTraversalClient.traverse()` raises `asyncio.TimeoutError`
- [ ] OTel span `knowledge_graph.traverse` is created for every invocation (including skipped paths)
- [ ] `graph_tokens_used` equals `GraphTraversalResult.total_tokens` on the happy path

## Dependencies

- TASK-US029-01 (`TraversalConfig`, `TraversalSettings`, `GraphContextItem`)
- TASK-US029-02 (`EntityLinker`)
- TASK-US029-03 (`GraphTraversalClient`)
- US-014 (`AgentState`, `ranked_context`, `execution_plan.remaining_tokens` — pre-existing)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `EntityLinker`, `GraphTraversalClient`, OTel tracer, and Langfuse via `AsyncMock`/`MagicMock`
- [ ] `mypy --strict` passes; no `ruff` lint errors
