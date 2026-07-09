# TASK-US007-01 — Implement `retrieval_agent` Node with `asyncio.gather` Parallel Dispatch

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US007-01 |
| User Story | US-007 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend |
| Priority | P0 |
| Points | 5 |
| Status | Draft |

## Description

Implement the `retrieval_agent` LangGraph node that reads the `execution_plan` from `AgentState`, selects the enabled connectors for the requested sources, and dispatches all connector `fetch()` calls concurrently via `asyncio.gather(return_exceptions=True)`. This is the core of the parallel retrieval step.

## Implementation Details

**Technology:** Python 3.11+, `asyncio`, `langgraph`

**File locations:**
- `src/agents/nodes/retrieval_agent.py` — `retrieval_node` async function
- `src/agents/retrieval/parallel_dispatcher.py` — `ParallelConnectorDispatcher` class
- `tests/agents/test_retrieval_agent.py`

**`retrieval_node` — LangGraph node function:**
```python
async def retrieval_node(state: AgentState) -> dict:
    plan = state["execution_plan"]
    prompt = state["prompt"]

    dispatcher = ParallelConnectorDispatcher(
        connector_registry=get_connector_registry(),
        timeout_seconds=settings.connector_timeout_seconds,   # default 5.0
    )

    results = await dispatcher.fetch_all(
        query=prompt,
        source_ids=plan["sources"],
        token_budget_per_source=plan.get("token_budget_per_source", {}),
    )

    return {
        "raw_context":    results.chunks,
        "ranked_context": results.chunks,   # ranking applied in EP-004; pass-through here
        "current_node":   "retrieval_agent",
        "status":         ExecutionStatus.RUNNING,
    }
```

**`ParallelConnectorDispatcher.fetch_all()`:**
```python
class ParallelConnectorDispatcher:
    def __init__(
        self,
        connector_registry: ConnectorRegistry,
        timeout_seconds: float = 5.0,
    ):
        self.registry = connector_registry
        self.timeout = timeout_seconds

    async def fetch_all(
        self,
        query: str,
        source_ids: list[str],
        token_budget_per_source: dict[str, int],
    ) -> FetchAllResult:
        connectors = [
            self.registry.get(src)
            for src in source_ids
            if self.registry.is_active(src)
        ]

        tasks = [
            self._fetch_one(connector, query, token_budget_per_source.get(connector.source_id))
            for connector in connectors
        ]

        # return_exceptions=True — a failing task returns the exception, not raises it
        raw_results: list[FetchResult | BaseException] = await asyncio.gather(
            *tasks, return_exceptions=True
        )

        chunks: list[ContextChunk] = []
        failed_sources: list[FailedSource] = []

        for connector, result in zip(connectors, raw_results):
            if isinstance(result, BaseException):
                failed_sources.append(FailedSource(
                    source_id=connector.source_id,
                    error_type=type(result).__name__,
                    message=str(result),
                ))
            else:
                chunks.extend(result.chunks)

        return FetchAllResult(chunks=chunks, failed_sources=failed_sources)
```

**`_fetch_one` — per-connector call with timeout (see TASK-US007-02):**
```python
async def _fetch_one(
    self,
    connector: BaseConnector,
    query: str,
    token_budget: int | None,
) -> FetchResult:
    return await asyncio.wait_for(
        connector.fetch(query=query, filters={"token_budget": token_budget}),
        timeout=self.timeout,
    )
```

**`FetchAllResult` and `ContextChunk` schemas:**
```python
class ContextChunk(BaseModel):
    chunk_id:    str
    source_id:   str
    content:     str
    token_count: int
    score:       float = 0.0
    metadata:    dict = {}     # file_path, timestamp, author, url

class FailedSource(BaseModel):
    source_id:  str
    error_type: str
    message:    str

class FetchAllResult(BaseModel):
    chunks:         list[ContextChunk]
    failed_sources: list[FailedSource]
```

## Acceptance Criteria

- [ ] All active connectors in `execution_plan["sources"]` are dispatched in a single `asyncio.gather` call
- [ ] `asyncio.gather` uses `return_exceptions=True` — one connector failing does not cancel others
- [ ] `FetchAllResult.chunks` is a flat list of `ContextChunk` from all successful connectors
- [ ] `FetchAllResult.failed_sources` lists every connector that raised an exception
- [ ] Inactive connectors (registry `is_active == False`) are skipped with no error
- [ ] Unit tests cover: all succeed, one fails, all fail, empty source list, inactive connector skipped

## Dependencies

- TASK-US006-01 (retrieval_agent node registered in graph; `execution_plan` in state from intent node)
- TASK-US007-02 (timeout enforcement inside `_fetch_one`)
- TASK-US007-04 (ConnectorRegistry provides active connectors)
- EP-007 US-021 (BaseConnector interface — `fetch()` signature)

## Definition of Done

- [ ] `retrieval_node` registered in `build_graph()` replacing the stub from TASK-US005-01
- [ ] Unit coverage ≥ 90% for `parallel_dispatcher.py`
- [ ] `mypy --strict` passes; `ContextChunk` and `FetchAllResult` fully typed
- [ ] `ruff` clean; no bare `except` clauses
