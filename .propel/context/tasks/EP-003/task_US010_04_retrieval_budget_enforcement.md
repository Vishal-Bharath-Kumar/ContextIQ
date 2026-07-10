# TASK-US010-04 — Retrieval Agent Per-Source Token Budget Enforcement

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US010-04 |
| User Story | US-010 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Update `ParallelConnectorDispatcher` (TASK-US007-01) so that each connector's response is truncated to its allocated quota from `ExecutionPlan.token_budget_per_source`. Also harden `retrieval_node` to read the typed `ExecutionPlan` rather than a raw dict. This ensures the Retrieval Agent fully honours the plan produced by the Intent Agent.

## Implementation Details

**Technology:** Python 3.11+, `tiktoken`, `langgraph>=0.2.0`

**File locations:**
- `src/agents/retrieval/parallel_dispatcher.py` — `_fetch_one()` token-cap logic
- `src/agents/nodes/retrieval_agent.py` — typed `ExecutionPlan` read
- `src/agents/retrieval/token_truncator.py` — `truncate_to_budget()` helper
- `tests/agents/retrieval/test_token_budget_enforcement.py`

**`truncate_to_budget()` helper:**

```python
# src/agents/retrieval/token_truncator.py
import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")   # module-level singleton

def truncate_to_budget(chunks: list[str], token_budget: int) -> list[str]:
    """Return chunks from the front of the list until `token_budget` is exhausted.

    Partial chunks are excluded; the caller receives complete chunks only.
    """
    kept: list[str] = []
    used = 0
    for chunk in chunks:
        chunk_tokens = len(_enc.encode(chunk))
        if used + chunk_tokens > token_budget:
            break
        kept.append(chunk)
        used += chunk_tokens
    return kept
```

**Updated `_fetch_one()` in `ParallelConnectorDispatcher`:**

```python
# src/agents/retrieval/parallel_dispatcher.py
from src.agents.retrieval.token_truncator import truncate_to_budget

async def _fetch_one(
    self,
    connector: BaseConnector,
    query: str,
    token_budget: int | None,
) -> ConnectorResult:
    try:
        async with asyncio.timeout(self.timeout):
            result = await connector.fetch(query)
        if token_budget is not None:
            result = result.model_copy(
                update={"chunks": truncate_to_budget(result.chunks, token_budget)}
            )
        return result
    except (asyncio.TimeoutError, Exception) as exc:
        return ConnectorResult(source_id=connector.source_id, chunks=[], error=str(exc))
```

**Updated `retrieval_node()` — typed plan access:**

```python
# src/agents/nodes/retrieval_agent.py
from src.agents.schemas.execution_plan import ExecutionPlan

async def retrieval_node(state: AgentState) -> dict:
    plan: ExecutionPlan = state["execution_plan"]   # typed; KeyError if missing → pipeline_failed

    dispatcher = ParallelConnectorDispatcher(
        connector_registry=get_connector_registry(),
        timeout_seconds=settings.connector_timeout_seconds,
    )

    results = await dispatcher.fetch_all(
        query=state["prompt"],
        source_ids=plan.sources,
        token_budget_per_source=plan.token_budget_per_source,
    )

    return {
        "raw_context":  results.chunks,
        "ranked_context": results.chunks,
        "current_node": "retrieval_agent",
        "status":       ExecutionStatus.RUNNING,
    }
```

**Source-list enforcement:**
- `ParallelConnectorDispatcher.fetch_all()` already filters `source_ids` against `registry.is_active()` (TASK-US007-01)
- The `plan.sources` list is the authoritative gating list; connectors not in `plan.sources` are never called regardless of registry status

## Acceptance Criteria

- [ ] Retrieval Agent queries only sources listed in `execution_plan.sources`; connectors absent from the list produce no network calls
- [ ] Response chunks from each connector are truncated to `token_budget_per_source[source_id]` tokens
- [ ] `truncate_to_budget(["chunk_a", "chunk_b"], budget)` returns only complete chunks that fit within the budget
- [ ] If a single chunk exceeds the budget, `truncate_to_budget` returns `[]` for that source (not a partial chunk)
- [ ] `retrieval_node` raises no `KeyError` when `execution_plan` is a typed `ExecutionPlan` instance
- [ ] Unit tests assert: exact source filtering, budget truncation boundary, zero-budget edge case

## Dependencies

- TASK-US010-01 (`ExecutionPlan` model — `plan.sources` and `plan.token_budget_per_source`)
- TASK-US010-03 (`generate_execution_plan()` — populates `AgentState.execution_plan` before retrieval runs)
- TASK-US007-01 (`ParallelConnectorDispatcher._fetch_one()` — extended, not replaced)
- TASK-US007-04 (Connector Registry — source active status check)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 85% for `src/agents/retrieval/token_truncator.py`
- [ ] Integration test: end-to-end retrieval with a two-source plan verifies per-source chunk count is within budget
- [ ] `tiktoken` encoding singleton is module-level — no re-initialisation per call
- [ ] `mypy --strict` passes; no `ruff` lint errors
