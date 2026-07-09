# TASK-US007-02 — Per-Connector Timeout Enforcement and Partial-Result Handling

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US007-02 |
| User Story | US-007 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Wrap each connector `fetch()` call with `asyncio.wait_for` to enforce a per-connector hard timeout (configurable, default 5 s). A timed-out connector must not block or cancel in-progress calls from other connectors, and its failure must be surfaced in the degraded-sources metadata without failing the overall retrieval step.

## Implementation Details

**Technology:** Python 3.11+, `asyncio`, `asyncio.wait_for`, `asyncio.TimeoutError`

**File locations:**
- `src/agents/retrieval/parallel_dispatcher.py` — `_fetch_one()` method (extends TASK-US007-01)
- `src/agents/retrieval/timeout_config.py` — per-source timeout overrides
- `tests/agents/test_connector_timeout.py`

**`_fetch_one` with timeout, cancellation safety, and metric:**
```python
async def _fetch_one(
    self,
    connector: BaseConnector,
    query: str,
    token_budget: int | None,
) -> FetchResult:
    source_id = connector.source_id
    t_start = time.monotonic()

    try:
        timeout = self._get_timeout(source_id)
        result = await asyncio.wait_for(
            connector.fetch(query=query, filters={"token_budget": token_budget}),
            timeout=timeout,
        )
        connector_fetch_duration.labels(
            source_id=source_id, status="success"
        ).observe(time.monotonic() - t_start)
        return result

    except asyncio.TimeoutError:
        connector_fetch_duration.labels(
            source_id=source_id, status="timeout"
        ).observe(time.monotonic() - t_start)
        connector_timeouts_total.labels(source_id=source_id).inc()
        raise ConnectorTimeoutError(
            source_id=source_id,
            timeout_seconds=self._get_timeout(source_id),
        )

    except Exception as e:
        connector_fetch_duration.labels(
            source_id=source_id, status="error"
        ).observe(time.monotonic() - t_start)
        connector_errors_total.labels(source_id=source_id, error_type=type(e).__name__).inc()
        raise
```

**`asyncio.wait_for` cancellation safety:** When `asyncio.wait_for` raises `TimeoutError`, it **cancels** the wrapped coroutine. If `connector.fetch()` does not handle `asyncio.CancelledError`, the underlying connection may not be cleaned up. Connectors must implement cleanup in a `try/finally` block (enforced in BaseConnector contract — TASK-US007-04).

**Per-source timeout overrides** (`timeout_config.py`):
```python
# Default 5 s; override per connector type via admin config
DEFAULT_TIMEOUT: float = 5.0

CONNECTOR_TIMEOUT_OVERRIDES: dict[str, float] = {
    "github":     8.0,   # GitHub API can be slow for large repos
    "confluence":  5.0,
    "jira":        5.0,
    "grafana":     3.0,   # Metrics API should be fast
}

def get_connector_timeout(source_id: str) -> float:
    connector_type = source_id.split(":")[0]   # e.g. "github:org/repo" → "github"
    return CONNECTOR_TIMEOUT_OVERRIDES.get(connector_type, DEFAULT_TIMEOUT)
```

**Prometheus metrics:**
```python
connector_fetch_duration = Histogram(
    "contextiq_connector_fetch_duration_seconds",
    "Per-connector fetch duration",
    ["source_id", "status"],   # status: success | timeout | error
    buckets=[0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0],
)

connector_timeouts_total = Counter(
    "contextiq_connector_timeouts_total",
    "Total connector fetch timeouts",
    ["source_id"],
)

connector_errors_total = Counter(
    "contextiq_connector_errors_total",
    "Total connector fetch errors by type",
    ["source_id", "error_type"],
)
```

**`ConnectorTimeoutError` (typed exception for `FailedSource` mapping):**
```python
class ConnectorTimeoutError(Exception):
    def __init__(self, source_id: str, timeout_seconds: float):
        self.source_id = source_id
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Connector '{source_id}' timed out after {timeout_seconds}s")
```

## Acceptance Criteria

- [ ] A connector that does not respond within the configured timeout raises `ConnectorTimeoutError` after exactly `timeout_seconds`
- [ ] A timed-out connector is recorded in `FetchAllResult.failed_sources` with `error_type = "ConnectorTimeoutError"`
- [ ] The remaining connectors' results are still returned in `FetchAllResult.chunks` when one times out
- [ ] Per-source timeout override takes effect: `grafana` connector times out at 3 s, not 5 s
- [ ] `contextiq_connector_timeouts_total{source_id="github:org/repo"}` increments on each GitHub timeout
- [ ] `CONNECTOR_TIMEOUT_SECONDS` env var overrides the global default (read by `timeout_config.py`)
- [ ] Unit tests: one connector times out (mock `asyncio.sleep(6)`) — other 3 connectors return results; total elapsed ≤ 5 s + 200 ms overhead

## Dependencies

- TASK-US007-01 (`_fetch_one` called from `fetch_all`; `ConnectorTimeoutError` caught by `return_exceptions=True`)
- US-036 (Prometheus scraping)
- EP-007 US-021 (BaseConnector cleanup contract in `fetch()`)

## Definition of Done

- [ ] `CONNECTOR_TIMEOUT_SECONDS` and per-type overrides documented in `.env.example`
- [ ] Unit test confirms timeout fires at correct time using `asyncio.timeout` mock
- [ ] Grafana "Connector Fetch Duration" heatmap panel added per source ID
- [ ] `mypy --strict` passes on `timeout_config.py` and `_fetch_one` signature
