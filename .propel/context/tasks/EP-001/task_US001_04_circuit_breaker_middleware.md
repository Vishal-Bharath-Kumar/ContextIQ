# TASK-US001-04 — Add Circuit-Breaker Middleware to MCP Endpoint

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US001-04 |
| User Story | US-001 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Resilience |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement a circuit-breaker middleware on the MCP gateway that tracks failure rates to downstream services (Agent Worker) and refuses new connections with a structured error when the circuit opens. This prevents cascading failures when the agent pipeline is unavailable.

## Implementation Details

**Technology:** Python 3.11+, `pybreaker` (or `tenacity` with circuit-breaker pattern), FastAPI middleware, Prometheus client

**File locations:**
- `src/gateway/middleware/circuit_breaker.py` — ASGI circuit-breaker middleware
- `src/gateway/state.py` — shared `CircuitBreaker` instance (application lifespan)
- `tests/gateway/test_circuit_breaker.py` — unit tests

**Key implementation steps:**

1. Define a `CircuitBreaker` instance with thresholds:
   ```python
   from pybreaker import CircuitBreaker, CircuitBreakerError

   gateway_breaker = CircuitBreaker(
       fail_max=5,           # open after 5 failures
       reset_timeout=60,     # attempt half-open after 60 s
       name="agent_pipeline"
   )
   ```

2. Wrap the downstream agent pipeline call (from `tools/call` handler) with `gateway_breaker`:
   ```python
   @gateway_breaker
   async def call_agent_pipeline(payload: dict) -> dict:
       ...
   ```

3. Catch `CircuitBreakerError` in the tool-call handler and return structured MCP error:
   ```json
   {
     "code": -32001,
     "message": "Service temporarily unavailable. Circuit open.",
     "data": {"retry_after_seconds": 60}
   }
   ```

4. Expose circuit state as a Prometheus gauge:
   ```python
   circuit_state_gauge = Gauge(
       "contextiq_circuit_breaker_state",
       "Circuit breaker state (0=closed, 1=open, 2=half-open)",
       ["name"]
   )
   ```
   Update the gauge via `pybreaker` state-change listener.

5. Log state transitions (`closed → open`, `open → half-open`, `half-open → closed`) at `WARNING` level.

## Acceptance Criteria

- [ ] 5 consecutive downstream failures within 60 s cause circuit to transition to `open`
- [ ] When circuit is open, new `tools/call` requests immediately receive the structured error (< 10 ms)
- [ ] After 60 s, one test request is allowed through (half-open state)
- [ ] Successful response in half-open state closes the circuit
- [ ] Prometheus metric `contextiq_circuit_breaker_state{name="agent_pipeline"}` reflects the correct state at all times
- [ ] Unit tests cover: normal flow, failure accumulation, open state refusal, half-open recovery

## Dependencies

- TASK-US001-01 (FastMCP server and ASGI middleware chain)
- TASK-US001-05 (OTel spans — add circuit state as span attribute)
- US-036 (Prometheus scraping configured)

## Definition of Done

- [ ] Circuit-breaker middleware integrated into application lifespan
- [ ] Unit tests pass; coverage ≥ 85% for `middleware/circuit_breaker.py`
- [ ] Grafana "Circuit Breaker State" panel added to the Platform Overview dashboard
- [ ] Chaos test: killing the agent-worker pod triggers circuit open within 60 s (verified in staging)
