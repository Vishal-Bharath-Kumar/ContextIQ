# TASK-US008-01 — Implement Per-Connector Circuit-Breaker

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US008-01 |
| User Story | US-008 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend / Resilience |
| Priority | P0 |
| Points | 5 |
| Status | Draft |

## Description

Implement a per-connector circuit-breaker that opens after 5 failures within 60 s, transitions to half-open after a configurable cool-down period, and closes on recovery. Each connector source ID gets its own isolated breaker instance stored in the `ConnectorRegistry` (TASK-US007-04), preventing a flapping connector from consuming retry budget during a full-degradation event.

## Implementation Details

**Technology:** Python 3.11+, `pybreaker`

**File locations:**
- `src/agents/retrieval/connector_circuit_breaker.py` — `ConnectorCircuitBreakerRegistry`
- `src/agents/retrieval/connector_registry.py` — breaker registry injected and wired to `_fetch_one` (extends TASK-US007-04)
- `tests/agents/test_connector_circuit_breaker.py`

**`ConnectorCircuitBreakerRegistry`:**
```python
from pybreaker import CircuitBreaker, CircuitBreakerError, CircuitBreakerListener

class ConnectorBreakerListener(CircuitBreakerListener):
    def __init__(self, source_id: str, publisher: StateEventPublisher):
        self.source_id = source_id
        self.publisher = publisher

    def state_change(self, cb: CircuitBreaker, old_state, new_state):
        logger.warning(
            "connector_circuit_breaker_state_change",
            source_id=self.source_id,
            from_state=old_state.name,
            to_state=new_state.name,
        )
        circuit_breaker_state_gauge.labels(source_id=self.source_id).set(
            _state_to_int(new_state.name)  # 0=closed, 1=open, 2=half_open
        )

class ConnectorCircuitBreakerRegistry:
    FAIL_MAX: int = 5
    RESET_TIMEOUT: int = 60   # seconds before transitioning open → half-open

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(self, source_id: str) -> CircuitBreaker:
        if source_id not in self._breakers:
            self._breakers[source_id] = CircuitBreaker(
                fail_max=self.FAIL_MAX,
                reset_timeout=self.RESET_TIMEOUT,
                name=f"connector:{source_id}",
                listeners=[ConnectorBreakerListener(source_id)],
            )
        return self._breakers[source_id]

    def is_open(self, source_id: str) -> bool:
        breaker = self._breakers.get(source_id)
        return breaker is not None and breaker.current_state == "open"

    def all_states(self) -> dict[str, str]:
        return {sid: cb.current_state for sid, cb in self._breakers.items()}
```

**Wiring into `_fetch_one` (replaces direct connector call):**
```python
async def _fetch_one(self, connector: BaseConnector, ...) -> FetchResult:
    breaker = self.breaker_registry.get_or_create(connector.source_id)

    @breaker   # pybreaker wraps the call; raises CircuitBreakerError when open
    async def _guarded_fetch():
        return await asyncio.wait_for(
            connector.fetch(query=query, filters=...),
            timeout=self._get_timeout(connector.source_id),
        )

    try:
        return await _guarded_fetch()
    except CircuitBreakerError:
        raise ConnectorCircuitOpenError(source_id=connector.source_id)
    except asyncio.TimeoutError:
        raise ConnectorTimeoutError(...)
    except Exception:
        raise
```

**`pybreaker` + `asyncio` compatibility:** `pybreaker` 1.x supports async callables directly when the decorated function is `async def`. Verify with `pybreaker>=1.0` in `pyproject.toml`.

**Threshold configuration via env:**
```
CONNECTOR_CB_FAIL_MAX=5
CONNECTOR_CB_RESET_TIMEOUT=60
```

## Acceptance Criteria

- [ ] After 5 consecutive failures from `github:myorg/myrepo` within 60 s, its circuit transitions to `open`
- [ ] Subsequent calls with an open circuit raise `ConnectorCircuitOpenError` immediately (< 5 ms — no network call)
- [ ] After `RESET_TIMEOUT` seconds, the circuit transitions to `half-open` and allows one test call
- [ ] A successful test call in `half-open` closes the circuit; a failed test call re-opens it
- [ ] Each connector's circuit-breaker is independent — `jira` circuit opening does not affect `github` circuit
- [ ] `CONNECTOR_CB_FAIL_MAX` and `CONNECTOR_CB_RESET_TIMEOUT` are read from env vars at startup
- [ ] Unit tests cover: failure accumulation to open, half-open recovery, half-open re-failure, independence between two connectors

## Dependencies

- TASK-US007-01 (`_fetch_one` is the integration point)
- TASK-US007-04 (`ConnectorRegistry` stores `ConnectorCircuitBreakerRegistry` as a field)
- `pybreaker>=1.0` added to `pyproject.toml`

## Definition of Done

- [ ] `ConnectorCircuitBreakerRegistry` is an application singleton in FastAPI lifespan
- [ ] Unit coverage ≥ 90% for `connector_circuit_breaker.py`
- [ ] Integration test: 5 consecutive mock failures → circuit opens → 6th call returns `ConnectorCircuitOpenError` with no network call
- [ ] `mypy --strict` passes; `pybreaker` stubs available or `py.typed` compatible
