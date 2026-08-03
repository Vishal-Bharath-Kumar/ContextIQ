# TASK-US029-05 — Integration Tests Covering All 6 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US029-05 |
| User Story | US-029 |
| Epic | EP-009 — Knowledge Graph Agent |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Write the integration and unit test suite covering all 6 US-029 acceptance criteria: Cypher traversal from ranked context, 5-edge-type traversal, configurable depth bound, `ranked_context` append with `source: knowledge_graph` label, 500 ms timeout enforcement, and token budget guard.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `AsyncMock`, `unittest.mock`

**File locations:**
- `tests/knowledge_graph/test_cypher_query_builder.py` — AC-1, AC-2, AC-3 (query shape)
- `tests/knowledge_graph/test_graph_traversal_client.py` — AC-5, AC-6 (timeout + budget)
- `tests/knowledge_graph/test_entity_linker.py` — AC-1 (seed resolution)
- `tests/knowledge_graph/test_knowledge_graph_node.py` — AC-1 through AC-6 (end-to-end node)

---

### Shared fixtures

```python
# tests/knowledge_graph/conftest.py  (extend existing conftest)
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid          import uuid4
from datetime      import datetime, timezone

from src.knowledge_graph.traversal.schemas  import GraphContextItem, GraphTraversalResult
from src.knowledge_graph.schemas.edge       import EdgeType

SEED_ID  = "a3f1c2b4d5e6f708"
TENANT   = "acme"

@pytest.fixture
def make_graph_item():
    def _make(entity_id=SEED_ID, hops=1, name="auth-service", tokens=30):
        return GraphContextItem(
            entity_id    = entity_id,
            entity_type  = "Service",
            name         = name,
            hops         = hops,
            path_summary = f"seed -[DEPENDS_ON]-> {name}",
            token_count  = tokens,
        )
    return _make

@pytest.fixture
def mock_traversal_result(make_graph_item):
    item = make_graph_item()
    return GraphTraversalResult(
        items             = [item],
        total_tokens      = 30,
        query_duration_ms = 120.0,
        seeds_used        = [SEED_ID],
        truncated         = False,
    )

@pytest.fixture
def ranked_context_with_entity_ids():
    return [
        {
            "text":      "auth-service depends on user-repository",
            "score":     0.95,
            "source_id": str(uuid4()),
            "metadata":  {"entity_ids": [SEED_ID]},
        }
    ]

@pytest.fixture
def ranked_context_no_entity_ids():
    return [
        {
            "text":      "the auth service had an outage last week",
            "score":     0.80,
            "source_id": str(uuid4()),
            "metadata":  {},
        }
    ]
```

---

### AC-1 — Cypher traversal triggered from ranked context seeds

```python
# tests/knowledge_graph/test_knowledge_graph_node.py
async def test_node_triggers_traversal_with_seeds_from_ranked_context(
    ranked_context_with_entity_ids, mock_traversal_result
):
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    mock_client = AsyncMock()
    mock_client.traverse         = AsyncMock(return_value=mock_traversal_result)
    mock_client.lookup_entity_ids = AsyncMock(return_value=[])

    with patch("src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
               return_value=mock_client), \
         patch("src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker") as MockLinker:
        linker_instance = AsyncMock()
        linker_instance.resolve = AsyncMock(return_value=[SEED_ID])
        MockLinker.return_value = linker_instance

        state = {
            "ranked_context": ranked_context_with_entity_ids,
            "execution_plan": {"remaining_tokens": 4000},
        }
        result = await knowledge_graph_node(state)

    mock_client.traverse.assert_awaited_once()
    assert result["graph_traversal_skipped"] is False
    assert len(result["graph_context_items"]) == 1
```

---

### AC-2 — All 5 edge types present in `TraversalConfig`

```python
# tests/knowledge_graph/test_cypher_query_builder.py
def test_traversal_config_includes_all_five_edge_types():
    from src.knowledge_graph.traversal.schemas import TraversalConfig
    from src.knowledge_graph.schemas.edge      import EdgeType

    config = TraversalConfig(seed_entity_ids=[SEED_ID], token_budget=1000)
    assert set(config.edge_types) == set(EdgeType)


def test_cypher_query_contains_edge_types_as_parameter():
    from src.knowledge_graph.traversal.query_builder import CypherQueryBuilder
    from src.knowledge_graph.traversal.schemas       import TraversalConfig

    config  = TraversalConfig(seed_entity_ids=[SEED_ID], token_budget=1000)
    query, params = CypherQueryBuilder().build_traversal(config)

    # Edge types must be in params, not in the query string
    assert "$edge_types" in query
    assert "DEPENDS_ON" not in query          # not interpolated
    assert "DEPENDS_ON" in params["edge_types"]
```

---

### AC-3 — Traversal depth bound

```python
def test_cypher_query_uses_max_depth_as_literal():
    from src.knowledge_graph.traversal.query_builder import CypherQueryBuilder
    from src.knowledge_graph.traversal.schemas       import TraversalConfig

    for depth in (1, 2, 3, 5):
        config = TraversalConfig(
            seed_entity_ids=[SEED_ID], token_budget=1000, max_depth=depth
        )
        query, _ = CypherQueryBuilder().build_traversal(config)
        assert f"*1..{depth}" in query


def test_traversal_config_rejects_depth_above_five():
    from src.knowledge_graph.traversal.schemas import TraversalConfig
    from pydantic import ValidationError
    import pytest

    with pytest.raises(ValidationError):
        TraversalConfig(seed_entity_ids=[SEED_ID], token_budget=1000, max_depth=6)
```

---

### AC-4 — Graph results appended to `ranked_context` with `source: knowledge_graph`

```python
async def test_graph_results_appended_to_ranked_context_with_source_label(
    ranked_context_with_entity_ids, mock_traversal_result
):
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    mock_client = AsyncMock()
    mock_client.traverse          = AsyncMock(return_value=mock_traversal_result)
    mock_client.lookup_entity_ids = AsyncMock(return_value=[])

    with patch("src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
               return_value=mock_client), \
         patch("src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker") as MockLinker:
        linker_instance = AsyncMock()
        linker_instance.resolve = AsyncMock(return_value=[SEED_ID])
        MockLinker.return_value = linker_instance

        initial_rc_len = len(ranked_context_with_entity_ids)
        state = {
            "ranked_context": ranked_context_with_entity_ids,
            "execution_plan": {"remaining_tokens": 4000},
        }
        result = await knowledge_graph_node(state)

    # ranked_context grew by the number of graph items
    assert len(result["ranked_context"]) == initial_rc_len + len(mock_traversal_result.items)
    # Every appended item has source="knowledge_graph"
    new_items = result["ranked_context"][initial_rc_len:]
    assert all(item["source"] == "knowledge_graph" for item in new_items)
```

---

### AC-5 — 500 ms timeout enforcement

```python
# tests/knowledge_graph/test_graph_traversal_client.py
async def test_traversal_client_raises_timeout_when_neo4j_is_slow():
    from src.knowledge_graph.traversal.neo4j_traversal_client import GraphTraversalClient
    from src.knowledge_graph.traversal.schemas                import TraversalConfig
    from src.knowledge_graph.stores.neo4j_store               import Neo4jSettings
    import asyncio, pytest

    async def slow_neo4j(*args, **kwargs):
        await asyncio.sleep(10)
        return []

    config = TraversalConfig(seed_entity_ids=[SEED_ID], token_budget=1000)

    with patch(
        "src.knowledge_graph.traversal.neo4j_traversal_client.GraphTraversalClient._run_query",
        side_effect=slow_neo4j,
    ):
        client = GraphTraversalClient(Neo4jSettings())
        # Monkey-patch query_timeout_s so the test doesn't wait 500ms
        client._settings = MagicMock(
            uri="bolt://x", username="neo4j", password="pw",
            database="neo4j", query_timeout_s=0.05
        )
        with pytest.raises(asyncio.TimeoutError):
            await client.traverse(config)


async def test_node_sets_skipped_true_on_timeout(ranked_context_with_entity_ids):
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node
    import asyncio

    mock_client = AsyncMock()
    mock_client.traverse          = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_client.lookup_entity_ids = AsyncMock(return_value=[])

    with patch("src.knowledge_graph.nodes.knowledge_graph_node.GraphTraversalClient",
               return_value=mock_client), \
         patch("src.knowledge_graph.nodes.knowledge_graph_node.EntityLinker") as MockLinker:
        linker_instance = AsyncMock()
        linker_instance.resolve = AsyncMock(return_value=[SEED_ID])
        MockLinker.return_value = linker_instance

        state  = {
            "ranked_context": ranked_context_with_entity_ids,
            "execution_plan": {"remaining_tokens": 4000},
        }
        result = await knowledge_graph_node(state)

    assert result["graph_traversal_skipped"] is True
    assert result["graph_tokens_used"]       == 0
```

---

### AC-6 — Token budget enforced; existing `ranked_context` unchanged on skip

```python
async def test_node_skips_traversal_when_budget_is_zero(ranked_context_with_entity_ids):
    from src.knowledge_graph.nodes.knowledge_graph_node import knowledge_graph_node

    state  = {
        "ranked_context": ranked_context_with_entity_ids,
        "execution_plan": {"remaining_tokens": 0},
    }
    result = await knowledge_graph_node(state)

    assert result["graph_traversal_skipped"] is True
    assert result["graph_tokens_used"]       == 0
    # ranked_context must be unchanged
    assert result["ranked_context"] == ranked_context_with_entity_ids


def test_apply_budget_truncates_items(make_graph_item):
    from src.knowledge_graph.traversal.neo4j_traversal_client import GraphTraversalClient
    from src.knowledge_graph.stores.neo4j_store               import Neo4jSettings

    client = GraphTraversalClient.__new__(GraphTraversalClient)
    items = [make_graph_item(entity_id=str(i) * 16, tokens=40) for i in range(5)]
    included, truncated, total = client._apply_budget(items, token_budget=100)
    assert len(included)  == 2       # 40 + 40 = 80 ≤ 100; third would make 120 > 100
    assert truncated      is True
    assert total          == 80


def test_apply_budget_no_truncation_when_budget_sufficient(make_graph_item):
    from src.knowledge_graph.traversal.neo4j_traversal_client import GraphTraversalClient

    client = GraphTraversalClient.__new__(GraphTraversalClient)
    items = [make_graph_item(entity_id=str(i) * 16, tokens=10) for i in range(5)]
    included, truncated, total = client._apply_budget(items, token_budget=100)
    assert len(included) == 5
    assert truncated     is False
    assert total         == 50


# Entity linker fast/slow path
async def test_entity_linker_fast_path_skips_llm(ranked_context_with_entity_ids):
    from src.knowledge_graph.traversal.entity_linker import EntityLinker

    mock_client = AsyncMock()
    linker      = EntityLinker(traversal_client=mock_client)
    seeds       = await linker.resolve(ranked_context_with_entity_ids)

    assert seeds == [SEED_ID]
    mock_client.lookup_entity_ids.assert_not_awaited()


async def test_entity_linker_slow_path_on_no_entity_ids(ranked_context_no_entity_ids):
    from src.knowledge_graph.traversal.entity_linker import EntityLinker
    import json

    mock_client = AsyncMock()
    mock_client.lookup_entity_ids = AsyncMock(return_value=[SEED_ID])

    llm_response = MagicMock()
    llm_response.choices = [MagicMock(message=MagicMock(
        content=json.dumps({"entity_names": ["auth-service"]})
    ))]

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=llm_response):
        linker = EntityLinker(traversal_client=mock_client)
        seeds  = await linker.resolve(ranked_context_no_entity_ids)

    mock_client.lookup_entity_ids.assert_awaited_once_with(["auth-service"])
    assert seeds == [SEED_ID]
```

## Acceptance Criteria

- [ ] All 6 AC-level tests pass in CI without live Neo4j or LLM
- [ ] `test_cypher_query_contains_edge_types_as_parameter` confirms no edge-type string interpolation
- [ ] `test_apply_budget_truncates_items` verifies greedy fill logic with correct cut-off
- [ ] `test_node_skips_traversal_when_budget_is_zero` confirms `ranked_context` is unchanged on skip
- [ ] `test_node_sets_skipped_true_on_timeout` confirms timeout is handled without raising to caller

## Dependencies

- TASK-US029-01 (`TraversalConfig`, `GraphContextItem`, `GraphTraversalResult`, `CypherQueryBuilder`)
- TASK-US029-02 (`EntityLinker`)
- TASK-US029-03 (`GraphTraversalClient`)
- TASK-US029-04 (`knowledge_graph_node`, `AgentState` extensions)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests use `AsyncMock`; no live services required in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
