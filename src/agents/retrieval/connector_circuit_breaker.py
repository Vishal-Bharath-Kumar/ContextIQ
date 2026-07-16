"""Per-connector circuit-breaker registry — TASK-US008-01.

Each connector ``source_id`` gets its own isolated :class:`pybreaker.CircuitBreaker`
instance.  After ``CONNECTOR_CB_FAIL_MAX`` consecutive failures within the
observation window the circuit transitions to ``open`` and subsequent calls
raise :class:`ConnectorCircuitOpenError` immediately without any network call.

After ``CONNECTOR_CB_RESET_TIMEOUT`` seconds the circuit transitions to
``half-open`` and allows one probe call; success closes the circuit, failure
re-opens it.

The registry is an application singleton injected into
:class:`~src.agents.retrieval.parallel_dispatcher.ParallelConnectorDispatcher`
at startup.

Environment variables
---------------------
``CONNECTOR_CB_FAIL_MAX``        — failure threshold (default 5)
``CONNECTOR_CB_RESET_TIMEOUT``   — cool-down seconds (default 60)
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import structlog
from pybreaker import CircuitBreaker, CircuitBreakerError, CircuitBreakerListener

from src.agents.retrieval.metrics import connector_circuit_breaker_state

__all__ = [
    "ConnectorBreakerListener",
    "ConnectorCircuitBreakerRegistry",
    "ConnectorCircuitOpenError",
    "async_call_with_breaker",
]

_logger = structlog.get_logger("contextiq.audit.circuit_breaker")

_STATE_TO_INT: dict[str, int] = {
    "closed": 0,
    "open": 1,
    "half-open": 2,
    "half_open": 2,
}


def _state_to_int(state_name: str) -> int:
    return _STATE_TO_INT.get(state_name, 0)


# ---------------------------------------------------------------------------
# Typed exception
# ---------------------------------------------------------------------------


class ConnectorCircuitOpenError(Exception):
    """Raised when a connector's circuit-breaker is open.

    Callers receive this immediately without any network call being attempted.
    """

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        super().__init__(f"Circuit breaker open for connector '{source_id}'")


# ---------------------------------------------------------------------------
# Listener
# ---------------------------------------------------------------------------


class ConnectorBreakerListener(CircuitBreakerListener):
    """Log and expose Prometheus metrics on circuit-breaker state transitions."""

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id

    def state_change(
        self,
        cb: CircuitBreaker,
        old_state: object,
        new_state: object,
    ) -> None:
        old_name = getattr(old_state, "name", str(old_state))
        new_name = getattr(new_state, "name", str(new_state))
        state_int = _state_to_int(new_name)
        connector_circuit_breaker_state.labels(connector_id=self.source_id).set(state_int)
        _logger.warning(
            "connector_circuit_state_change",
            connector_id=self.source_id,
            from_state=old_name,
            to_state=new_name,
            fail_max=cb.fail_max,
            reset_timeout=cb.reset_timeout,
        )

    def failure(self, cb: CircuitBreaker, exc: BaseException) -> None:  # noqa: ARG002
        _logger.debug(
            "connector_circuit_breaker_failure",
            connector_id=self.source_id,
            error=str(exc),
        )

    def success(self, cb: CircuitBreaker) -> None:  # noqa: ARG002
        _logger.debug(
            "connector_circuit_breaker_success",
            connector_id=self.source_id,
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ConnectorCircuitBreakerRegistry:
    """Application-scoped registry of per-connector :class:`~pybreaker.CircuitBreaker` instances.

    Threshold values are read from environment variables at construction time
    so that a single process-level singleton picks them up at startup.

    Usage
    -----
    ::

        registry = ConnectorCircuitBreakerRegistry()
        breaker = registry.get_or_create("github:myorg/myrepo")
    """

    FAIL_MAX: int = int(os.environ.get("CONNECTOR_CB_FAIL_MAX", "5"))
    RESET_TIMEOUT: int = int(os.environ.get("CONNECTOR_CB_RESET_TIMEOUT", "60"))

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(self, source_id: str) -> CircuitBreaker:
        """Return the :class:`~pybreaker.CircuitBreaker` for *source_id*, creating it on first access."""
        if source_id not in self._breakers:
            self._breakers[source_id] = CircuitBreaker(
                fail_max=self.FAIL_MAX,
                reset_timeout=self.RESET_TIMEOUT,
                name=f"connector:{source_id}",
                listeners=[ConnectorBreakerListener(source_id)],
            )
        return self._breakers[source_id]

    def is_open(self, source_id: str) -> bool:
        """Return ``True`` when the circuit for *source_id* is currently open."""
        breaker = self._breakers.get(source_id)
        return breaker is not None and breaker.current_state == "open"

    def all_states(self) -> dict[str, str]:
        """Return a snapshot of ``{source_id: state_name}`` for all tracked connectors."""
        return {sid: cb.current_state for sid, cb in self._breakers.items()}


# ---------------------------------------------------------------------------
# Asyncio-compatible execution helper
# ---------------------------------------------------------------------------


async def async_call_with_breaker(
    breaker: CircuitBreaker,
    source_id: str,
    coro_factory: object,
) -> object:
    """Execute *coro_factory()* under circuit-breaker protection (asyncio-compatible).

    ``pybreaker``'s built-in decorator cannot track ``async`` function outcomes
    because it receives only the coroutine object (not the awaited result).
    This helper replicates ``CircuitBreakerState.call()`` semantics for asyncio:

    1. If the circuit is open and the cool-down has **not** elapsed → raise
       :class:`ConnectorCircuitOpenError` immediately (no network call).
    2. If the circuit is open and the cool-down **has** elapsed → transition
       to ``half-open`` and allow one probe call.
    3. Execute *coro_factory()* asynchronously.
    4. On success: notify the state machine to close/stay closed.
    5. On failure: notify the state machine; circuit may transition to ``open``.

    Args:
        breaker:        The :class:`~pybreaker.CircuitBreaker` instance to consult.
        source_id:      Connector identifier used in error messages.
        coro_factory:   Zero-argument callable that returns a coroutine.

    Raises:
        ConnectorCircuitOpenError: when the circuit is open and cool-down has
            not elapsed.
        Any exception raised by *coro_factory()*.
    """
    # -- State gate ----------------------------------------------------------
    if breaker.current_state == "open":
        opened_at = breaker._state_storage.opened_at  # type: ignore[attr-defined]
        timeout_delta = timedelta(seconds=breaker.reset_timeout)
        if opened_at and datetime.now(UTC) < opened_at + timeout_delta:
            raise ConnectorCircuitOpenError(source_id)
        # Cool-down elapsed → probe with half-open
        breaker.half_open()

    # -- Execute async call --------------------------------------------------
    try:
        result = await coro_factory()  # type: ignore[misc]
    except BaseException as exc:
        # Only record as a failure if pybreaker considers it a system error
        if breaker.is_system_error(exc):
            breaker._inc_counter()  # type: ignore[attr-defined]
            for listener in breaker.listeners:
                listener.failure(breaker, exc)
            try:
                breaker.state.on_failure(exc)
            except CircuitBreakerError:
                # on_failure raises CircuitBreakerError when it opens the circuit;
                # suppress it here and let the original exception propagate.
                pass
        raise
    else:
        # Record success and allow state machine to close/stay closed
        breaker._state_storage.reset_counter()  # type: ignore[attr-defined]
        breaker.state.on_success()
        for listener in breaker.listeners:
            listener.success(breaker)
        return result
