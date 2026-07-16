"""
Shared application state for the ContextIQ MCP Gateway.

TASK-US001-04: Circuit-breaker instance and Prometheus gauge, initialised once
at import time and referenced by the middleware and the tool-call handler.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pybreaker
from prometheus_client import Gauge

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metric
# ---------------------------------------------------------------------------

circuit_state_gauge: Gauge = Gauge(
    "contextiq_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half-open)",
    ["name"],
)

# ---------------------------------------------------------------------------
# State-change listener
# ---------------------------------------------------------------------------

_STATE_VALUES: dict[str, int] = {
    pybreaker.STATE_CLOSED: 0,    # "closed"
    pybreaker.STATE_OPEN: 1,      # "open"
    pybreaker.STATE_HALF_OPEN: 2, # "half-open"
}


class _StateChangeListener(pybreaker.CircuitBreakerListener):
    """Update the Prometheus gauge and emit WARNING logs on every transition."""

    def state_change(
        self,
        cb: pybreaker.CircuitBreaker,
        old_state: pybreaker.CircuitBreakerState | None,
        new_state: pybreaker.CircuitBreakerState,
    ) -> None:
        old_name = old_state.name if old_state is not None else "none"
        new_name = new_state.name
        logger.warning(
            "Circuit breaker '%s' state: %s → %s",
            cb.name,
            old_name,
            new_name,
        )
        circuit_state_gauge.labels(name=cb.name).set(
            _STATE_VALUES.get(new_name, 0)
        )


# ---------------------------------------------------------------------------
# Circuit-breaker singleton
# ---------------------------------------------------------------------------

gateway_breaker: pybreaker.CircuitBreaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=60,
    name="agent_pipeline",
    listeners=[_StateChangeListener()],
)

# Seed the gauge so Prometheus can scrape the initial state immediately.
circuit_state_gauge.labels(name="agent_pipeline").set(0)  # closed
