"""Redis-backed sliding-window circuit breaker for model provider calls (TASK-US020-03)."""

from __future__ import annotations

import time
import uuid
from enum import StrEnum

from redis.asyncio import Redis

from src.model_invoker.config import InvokerSettings


class CircuitState(StrEnum):
    CLOSED = "closed"        # normal operation — requests permitted
    OPEN = "open"            # tripped — requests blocked for this provider
    HALF_OPEN = "half_open"  # one probe request permitted to test recovery


class ProviderCircuitBreaker:
    """
    Tracks per-provider failures in a Redis sorted-set sliding window.

    Key schema:
        contextiq:circuit_breaker:{provider}:failures  — sorted set of epoch-ms timestamps
        contextiq:circuit_breaker:{provider}:state     — "open" | "half_open"; absent ↔ CLOSED
    """

    def __init__(self, redis: Redis, settings: InvokerSettings | None = None) -> None:
        self._redis = redis
        self._settings = settings or InvokerSettings()

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _failures_key(self, provider: str) -> str:
        return f"contextiq:circuit_breaker:{provider}:failures"

    def _state_key(self, provider: str) -> str:
        return f"contextiq:circuit_breaker:{provider}:state"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def is_available(self, provider: str) -> bool:
        """Return False if the circuit is OPEN for this provider."""
        raw_state = await self._redis.get(self._state_key(provider))
        if raw_state == b"open":
            return False
        if raw_state == b"half_open":
            return True  # allow one probe; FallbackInvoker must record the outcome
        return True  # CLOSED — normal operation

    async def record_failure(self, provider: str) -> CircuitState:
        """
        Record a failure timestamp in the sliding window.

        Evicts entries older than ``circuit_window_s`` seconds, then appends
        the current timestamp.  If the failure count reaches
        ``circuit_failure_threshold`` the state key is set to ``"open"`` with
        a TTL of ``circuit_open_ttl_s`` seconds.

        Returns the resulting CircuitState.
        """
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - (self._settings.circuit_window_s * 1000)

        failures_key = self._failures_key(provider)
        # Use a unique member so concurrent/same-ms failures are not deduplicated
        member = f"{now_ms}:{uuid.uuid4().hex}"

        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(failures_key, "-inf", cutoff)           # evict stale entries
        pipe.zadd(failures_key, {member: now_ms})                     # record new failure
        pipe.zcard(failures_key)                                       # count within window
        pipe.expire(failures_key, self._settings.circuit_window_s * 2)
        results = await pipe.execute()

        count: int = results[2]
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
        Record a successful call.

        Clears the OPEN/HALF_OPEN state key and resets the failure sorted set
        so the provider starts fresh.
        """
        pipe = self._redis.pipeline()
        pipe.delete(self._state_key(provider))
        pipe.delete(self._failures_key(provider))
        await pipe.execute()
