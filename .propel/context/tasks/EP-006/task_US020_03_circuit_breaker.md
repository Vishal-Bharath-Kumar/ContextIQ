# TASK-US020-03 — `ProviderCircuitBreaker`: Redis-Backed Sliding Window

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US020-03 |
| User Story | US-020 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend / Caching |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `ProviderCircuitBreaker` — a Redis-backed circuit breaker that tracks consecutive provider failures in a 60-second sliding window and opens the circuit after 5 failures, preventing further requests to that provider until the window clears. Satisfies US-020 AC-5.

## Implementation Details

**Technology:** Python 3.11+, `redis.asyncio>=5.0`

**File locations:**
- `src/model_invoker/circuit_breaker.py` — `CircuitState`, `ProviderCircuitBreaker`
- `src/model_invoker/config.py` — `CircuitBreakerSettings` extension of `InvokerSettings`
- `tests/model_invoker/test_circuit_breaker.py` — `fakeredis.aioredis`

**`CircuitState`:**

```python
# src/model_invoker/circuit_breaker.py
from enum import StrEnum

class CircuitState(StrEnum):
    CLOSED     = "closed"      # normal operation — requests permitted
    OPEN       = "open"        # tripped — requests blocked for this provider
    HALF_OPEN  = "half_open"   # one probe request permitted to test recovery
```

**Redis key design:**

```
contextiq:circuit_breaker:{provider}:failures  — Sorted set; members = epoch-ms timestamps of each failure
contextiq:circuit_breaker:{provider}:state     — String; "open" | "half_open"; absent ↔ CLOSED
```

The sorted set uses failure timestamps as both member and score (`ZADD key <epoch_ms> <epoch_ms>`). The sliding window is computed by removing entries older than `now - window_s` with `ZREMRANGEBYSCORE` before counting.

**`CircuitBreakerSettings`:**

```python
# src/model_invoker/config.py  — extend InvokerSettings
class InvokerSettings(BaseSettings):
    ...                                         # existing fields
    circuit_failure_threshold: int   = 5        # failures within window before OPEN
    circuit_window_s:          int   = 60       # sliding window duration (seconds)
    circuit_open_ttl_s:        int   = 60       # how long OPEN state persists before HALF_OPEN
```

**`ProviderCircuitBreaker`:**

```python
# src/model_invoker/circuit_breaker.py
import time
from redis.asyncio import Redis
from src.model_invoker.config import InvokerSettings

class ProviderCircuitBreaker:
    def __init__(self, redis: Redis, settings: InvokerSettings | None = None) -> None:
        self._redis    = redis
        self._settings = settings or InvokerSettings()

    def _failures_key(self, provider: str) -> str:
        return f"contextiq:circuit_breaker:{provider}:failures"

    def _state_key(self, provider: str) -> str:
        return f"contextiq:circuit_breaker:{provider}:state"

    async def is_available(self, provider: str) -> bool:
        """Return False if the circuit is OPEN for this provider."""
        raw_state = await self._redis.get(self._state_key(provider))
        if raw_state == b"open":
            return False
        if raw_state == b"half_open":
            return True   # allow one probe; FallbackInvoker must record the outcome
        return True        # CLOSED — normal operation

    async def record_failure(self, provider: str) -> CircuitState:
        """
        Record a failure timestamp in the sliding window.
        Opens the circuit if the failure count reaches threshold.
        Returns the resulting CircuitState.
        """
        now_ms  = int(time.time() * 1000)
        cutoff  = now_ms - (self._settings.circuit_window_s * 1000)

        failures_key = self._failures_key(provider)

        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(failures_key, "-inf", cutoff)     # evict old entries
        pipe.zadd(failures_key, {str(now_ms): now_ms})          # record new failure
        pipe.zcard(failures_key)                                 # count within window
        pipe.expire(failures_key, self._settings.circuit_window_s * 2)
        results = await pipe.execute()

        count = results[2]
        if count >= self._settings.circuit_failure_threshold:
            await self._redis.set(
                self._state_key(provider),
                "open",
                ex=self._settings.circuit_open_ttl_s,
            )
            return CircuitState.OPEN
        return CircuitState.CLOSED

    async def record_success(self, provider: str) -> None:
        """
        Record a successful call. Clears OPEN/HALF_OPEN state and resets failure window.
        """
        pipe = self._redis.pipeline()
        pipe.delete(self._state_key(provider))
        pipe.delete(self._failures_key(provider))
        await pipe.execute()
```

**State transition diagram:**

```
CLOSED ──(5 failures / 60 s)──► OPEN ──(TTL expires)──► HALF_OPEN
  ▲                                                          │
  └───────────────(probe success)───────────────────────────┘
```

`HALF_OPEN` is implicit: when the `circuit_open_ttl_s` TTL on the `state` key expires, `is_available()` returns `True` again (absent state = CLOSED). `FallbackInvoker` must call `record_success()` on a probe success to clear the failure window, or `record_failure()` on a probe failure to re-open the circuit.

**Atomicity note:**

The pipeline executes `ZREMRANGEBYSCORE` + `ZADD` + `ZCARD` atomically in a single Redis round-trip. This is sufficient for the single-instance deployment assumed by Phase 1; a Lua script or Redis transaction would be required for strict multi-instance consistency in Phase 2.

## Acceptance Criteria

- [ ] `is_available()` returns `True` when no state key exists (CLOSED)
- [ ] `is_available()` returns `False` immediately after the state key is set to `"open"`
- [ ] `record_failure()` returns `CircuitState.OPEN` after exactly `circuit_failure_threshold` failures within the window
- [ ] Failures older than `circuit_window_s` seconds are not counted
- [ ] `record_success()` deletes both the state key and the failures sorted set
- [ ] `is_available()` returns `True` after `circuit_open_ttl_s` seconds (TTL expiry simulated with `fakeredis` `time_travel`)
- [ ] All operations use pipelining — no more than 2 Redis round-trips per `record_failure()` call

## Dependencies

- TASK-US020-01 (`FallbackSettings` — `circuit_failure_threshold`, `circuit_window_s`, `circuit_open_ttl_s` added to `InvokerSettings`)
- TASK-US020-02 (`extract_provider()` — `provider` argument derived from model_id)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests use `fakeredis.aioredis`; no live Redis in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
