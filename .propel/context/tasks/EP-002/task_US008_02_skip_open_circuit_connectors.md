# TASK-US008-02 — Skip Open-Circuit Connectors Before Dispatch

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US008-02 |
| User Story | US-008 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Extend `ParallelConnectorDispatcher.fetch_all()` to check each connector's circuit-breaker state before dispatching. Connectors with an open circuit are immediately added to `failed_sources` with reason `circuit_open` — no `asyncio.Task` is created for them, saving the timeout budget for genuinely reachable sources.

## Implementation Details

**Technology:** Python 3.11+, `asyncio`

**File locations:**
- `src/agents/retrieval/parallel_dispatcher.py` — `fetch_all()` pre-dispatch filter (extends TASK-US007-01)
- `tests/agents/test_circuit_breaker_skip.py`

**Updated `fetch_all()` with pre-dispatch circuit check:**
```python
async def fetch_all(
    self,
    query: str,
    source_ids: list[str],
    token_budget_per_source: dict[str, int],
) -> FetchAllResult:
    # Separate connectors into dispatchable and pre-failed
    dispatchable: list[BaseConnector] = []
    pre_failed:   list[FailedSource]  = []

    for source_id in source_ids:
        if not self.registry.is_active(source_id):
            continue   # not registered — silently skip (health-check excluded it)

        connector = self.registry.get(source_id)

        if self.breaker_registry.is_open(source_id):
            # Circuit is open — skip dispatch immediately, no network call
            pre_failed.append(FailedSource(
                source_id=source_id,
                error_type="ConnectorCircuitOpenError",
                message=f"Circuit breaker open for '{source_id}' — skipping dispatch",
            ))
            connector_circuit_skip_total.labels(source_id=source_id).inc()
            continue

        dispatchable.append(connector)

    # Dispatch only the healthy connectors
    tasks = [
        self._fetch_one(connector, query, token_budget_per_source.get(connector.source_id))
        for connector in dispatchable
    ]
    raw_results: list[FetchResult | BaseException] = await asyncio.gather(
        *tasks, return_exceptions=True
    )

    # Collect runtime failures from dispatchable connectors
    runtime_failed: list[FailedSource] = []
    chunks: list[ContextChunk] = []
    for connector, result in zip(dispatchable, raw_results):
        if isinstance(result, BaseException):
            runtime_failed.append(FailedSource(
                source_id=connector.source_id,
                error_type=type(result).__name__,
                message=str(result),
            ))
        else:
            chunks.extend(result.chunks)

    return FetchAllResult(
        chunks=chunks,
        failed_sources=pre_failed + runtime_failed,
    )
```

**Key behavioural contracts:**
- An open-circuit connector is never dispatched — saves the full timeout budget (up to 8 s per skipped connector)
- Open-circuit connectors appear in `failed_sources` with `error_type = "ConnectorCircuitOpenError"`, not silently dropped
- Skipping is not an error at the pipeline level — it is expected degraded behaviour

**Prometheus counter for skip tracking:**
```python
connector_circuit_skip_total = Counter(
    "contextiq_connector_circuit_skip_total",
    "Connector calls skipped due to open circuit breaker",
    ["source_id"],
)
```

**Half-open re-admission:** When the circuit is in `half-open` state, `pybreaker` allows exactly one call through. `is_open()` returns `False` for `half-open` (only truly `open` state returns `True`), so the half-open test call is dispatched normally via `_fetch_one`.

## Acceptance Criteria

- [ ] A connector with an open circuit breaker is not included in the `asyncio.gather` task list (verified via task-count assertion in test)
- [ ] Open-circuit connector appears in `FetchAllResult.failed_sources` with `error_type = "ConnectorCircuitOpenError"`
- [ ] When all connectors have open circuits, `FetchAllResult.chunks` is empty and `failed_sources` contains all skipped connectors
- [ ] `contextiq_connector_circuit_skip_total{source_id}` increments for each skipped connector
- [ ] Half-open connector (`is_open() == False`) is included in dispatch as a normal call
- [ ] Unit tests: 1 open + 2 closed connectors → gather called with 2 tasks; open connector in `failed_sources`

## Dependencies

- TASK-US008-01 (`ConnectorCircuitBreakerRegistry.is_open()`)
- TASK-US007-01 (`fetch_all()` structure being modified)
- TASK-US007-04 (`ConnectorRegistry` for active connector lookup)

## Definition of Done

- [ ] Modified `fetch_all()` merged; pre-dispatch check is the first operation after active-connector filter
- [ ] Unit test asserts `asyncio.gather` receives exactly `N - open_count` tasks
- [ ] `connector_circuit_skip_total` metric confirmed in Prometheus after staging chaos test
- [ ] `mypy --strict` passes on modified `parallel_dispatcher.py`
