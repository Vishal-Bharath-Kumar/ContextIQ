# TASK-US008-04 — Connector Failure Metrics: `connector_failure_count` and Circuit-Breaker State

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US008-04 |
| User Story | US-008 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Observability |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Register and populate the `connector_failure_count` Prometheus counter required by AC-4, expose circuit-breaker state as a Prometheus gauge, and emit a structured log on every circuit-state transition. All three signals feed the Grafana panel required by AC-6.

## Implementation Details

**Technology:** Python 3.11+, `prometheus-client`, `structlog`

**File locations:**
- `src/agents/retrieval/metrics.py` — all connector-related Prometheus metrics (consolidates metrics from TASK-US007-02)
- `src/agents/retrieval/connector_circuit_breaker.py` — `ConnectorBreakerListener` emits gauge + log (extends TASK-US008-01)
- `tests/agents/test_connector_metrics.py`

**Consolidated metrics module (`metrics.py`):**
```python
# --- Failure counter (AC-4) ---
connector_failure_count = Counter(
    "contextiq_connector_failure_count",
    "Total connector fetch failures (timeout + errors + circuit open skips)",
    ["connector_id", "failure_type"],
    # failure_type: timeout | error | circuit_open
)

# --- Circuit-breaker state gauge (AC-5/6) ---
connector_circuit_breaker_state = Gauge(
    "contextiq_connector_circuit_breaker_state",
    "Circuit breaker state per connector (0=closed, 1=open, 2=half_open)",
    ["connector_id"],
)

# --- Fetch duration histogram (from TASK-US007-02 — kept here as single source) ---
connector_fetch_duration_seconds = Histogram(
    "contextiq_connector_fetch_duration_seconds",
    "Per-connector fetch duration in seconds",
    ["connector_id", "status"],
    buckets=[0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0],
)
```

**Failure counter increment sites:**

| Failure event | Where incremented | `failure_type` label |
|---|---|---|
| `asyncio.TimeoutError` | `_fetch_one` except block | `timeout` |
| Any other exception from `connector.fetch()` | `_fetch_one` except block | `error` |
| Circuit-open skip (pre-dispatch) | `fetch_all` circuit-skip branch | `circuit_open` |

```python
# In _fetch_one — on TimeoutError:
connector_failure_count.labels(
    connector_id=connector.source_id, failure_type="timeout"
).inc()

# In fetch_all — on circuit-open skip:
connector_failure_count.labels(
    connector_id=source_id, failure_type="circuit_open"
).inc()
```

**Circuit-breaker state gauge via `ConnectorBreakerListener`:**
```python
def state_change(self, cb: CircuitBreaker, old_state, new_state):
    state_int = {"closed": 0, "open": 1, "half_open": 2}.get(new_state.name, -1)
    connector_circuit_breaker_state.labels(connector_id=self.source_id).set(state_int)

    structlog.get_logger("contextiq.audit.circuit_breaker").warning(
        "connector_circuit_state_change",
        connector_id=self.source_id,
        from_state=old_state.name,
        to_state=new_state.name,
        fail_max=cb.fail_max,
        reset_timeout=cb.reset_timeout,
    )
```

**Initial gauge population at startup:** When a connector is registered, initialise its gauge to `0` (closed):
```python
def register(self, source_id: str, connector: BaseConnector) -> None:
    ...
    connector_circuit_breaker_state.labels(connector_id=source_id).set(0)
```

**`connector_failure_count` naming note:** AC-4 specifies `connector_failure_count{connector_id}` — this matches the label name `connector_id` used throughout. The counter replaces the separate `connector_errors_total` and `connector_timeouts_total` from TASK-US007-02 (which are merged here under a unified `failure_type` label).

## Acceptance Criteria

- [ ] `contextiq_connector_failure_count{connector_id="jira:myproject", failure_type="timeout"}` increments on each Jira timeout
- [ ] `contextiq_connector_failure_count{connector_id="github:org/repo", failure_type="circuit_open"}` increments each time the open circuit is skipped
- [ ] `contextiq_connector_circuit_breaker_state{connector_id="jira:myproject"}` equals `1` when circuit is open
- [ ] `contextiq_connector_circuit_breaker_state` equals `0` (closed) for all connectors at startup (before any failures)
- [ ] A structured `connector_circuit_state_change` log is emitted with `from_state` and `to_state` on every transition
- [ ] Metrics are exposed at `/metrics` on the agent-worker service and scrapeable by Prometheus

## Dependencies

- TASK-US008-01 (`ConnectorBreakerListener` where gauge update is triggered)
- TASK-US008-02 (circuit-skip branch increments `connector_failure_count`)
- TASK-US007-02 (timeout/error branches updated to use consolidated metric names)

## Definition of Done

- [ ] `metrics.py` is the single import source for all connector metrics — no duplicate metric definitions
- [ ] `connector_errors_total` and `connector_timeouts_total` from TASK-US007-02 removed and replaced with `connector_failure_count`
- [ ] Unit tests assert counter increments for all 3 `failure_type` values
- [ ] Prometheus scrape confirmed in staging: `curl http://agent-worker/metrics | grep connector_failure_count`
