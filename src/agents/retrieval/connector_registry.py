"""ConnectorRegistry — source-ID-keyed runtime connector store.

TASK-US007-04: Connector Registry: Active Connector Selection from Execution Plan.

Maps source IDs from the ``execution_plan`` to live ``BaseConnector`` instances,
tracks per-connector health state, and exposes helper methods used by
``ParallelConnectorDispatcher`` to skip unhealthy connectors.
"""
from __future__ import annotations

import logging

from src.agents.retrieval.connector_circuit_breaker import ConnectorCircuitBreakerRegistry
from src.agents.retrieval.metrics import connector_circuit_breaker_state
from src.connector_sdk.base import BaseConnector

_logger = logging.getLogger(__name__)


class ConnectorNotFoundError(KeyError):
    """Raised by :meth:`ConnectorRegistry.get` when *source_id* is not registered."""

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        super().__init__(f"No connector registered for source_id '{source_id}'")


class ConnectorRegistry:
    """Runtime registry that maps source IDs to ``BaseConnector`` instances.

    Instances are registered at application startup by :class:`ConnectorLoader`
    and kept healthy by the :func:`health_check_loop` background task.

    Usage
    -----
    ::

        registry = ConnectorRegistry()
        # populated by ConnectorLoader.load() at startup
        connector = registry.get("github:myorg/myrepo")
        if registry.is_active("jira:myproject"):
            ...
    """

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}
        self._health: dict[str, bool] = {}
        self.breaker_registry: ConnectorCircuitBreakerRegistry = ConnectorCircuitBreakerRegistry()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def register(self, source_id: str, connector: BaseConnector) -> None:
        """Register *connector* under *source_id* and mark it healthy.

        Re-registering an existing *source_id* replaces the previous connector
        and resets its health to ``True`` (used for dynamic re-registration).
        """
        self._connectors[source_id] = connector
        self._health[source_id] = True
        connector_circuit_breaker_state.labels(connector_id=source_id).set(0)
        _logger.info("connector_registered", extra={"source_id": source_id})

    def unregister(self, source_id: str) -> None:
        """Remove *source_id* from the registry (e.g. connector disabled via Admin API)."""
        self._connectors.pop(source_id, None)
        self._health.pop(source_id, None)
        _logger.info("connector_unregistered", extra={"source_id": source_id})

    def set_health(self, source_id: str, healthy: bool) -> None:
        """Update the health flag for *source_id*; called by :func:`health_check_loop`."""
        if source_id in self._connectors:
            self._health[source_id] = healthy

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, source_id: str) -> BaseConnector:
        """Return the connector registered under *source_id*.

        Raises:
            ConnectorNotFoundError: when *source_id* is not registered.
        """
        if source_id not in self._connectors:
            raise ConnectorNotFoundError(source_id)
        return self._connectors[source_id]

    def is_active(self, source_id: str) -> bool:
        """Return ``True`` when *source_id* is registered *and* healthy."""
        return source_id in self._connectors and self._health.get(source_id, False)

    def active_source_ids(self) -> list[str]:
        """Return source IDs of all healthy registered connectors."""
        return [sid for sid in self._connectors if self._health.get(sid, False)]
