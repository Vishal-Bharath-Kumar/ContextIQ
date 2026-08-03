"""
ConnectorRegistry and ConnectorRecord — runtime connector management.

TASK-US021-02: Entry-Point Auto-Discovery and ConnectorRegistry.

The registry is the single source of truth for all connector instances.
It is populated once at application startup via ``ConnectorRegistry.load()``
and attached to ``app.state.connector_registry`` by the FastAPI lifespan.
ConnectorHealthPoller (TASK-US021-03) calls ``set_health()`` to update
runtime state.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from src.connector_sdk.base import BaseConnector
from src.connector_sdk.discovery import discover_connectors

_logger = logging.getLogger(__name__)


@dataclass
class ConnectorRecord:
    """Runtime metadata for a single registered connector."""

    connector_id: str
    cls: type[BaseConnector]
    instance: BaseConnector
    enabled: bool = field(default=True)
    last_health: bool | None = field(default=None)
    last_checked: datetime | None = field(default=None)


class ConnectorRegistry:
    """Discover, instantiate, and manage all registered connectors.

    Usage
    -----
    ::

        registry = ConnectorRegistry()
        await registry.load()
        app.state.connector_registry = registry
    """

    def __init__(self) -> None:
        self._records: dict[str, ConnectorRecord] = {}

    async def load(
        self,
        connector_classes: dict[str, type[BaseConnector]] | None = None,
    ) -> None:
        """Discover connectors, instantiate each, and call ``authenticate()``.

        Parameters
        ----------
        connector_classes:
            Optional explicit mapping of ``{connector_id: ConnectorClass}``.
            When supplied (e.g. in tests) entry-point discovery is skipped.
            When ``None`` (default) entry points are resolved at runtime.

        Notes
        -----
        Connectors whose ``authenticate()`` raises are registered with
        ``enabled=False`` so the rest of the platform remains available.
        Connectors that fail to even instantiate (e.g. missing required
        deployment config, such as an unset ``base_url``) are skipped
        entirely with a warning rather than crashing application startup.
        """
        classes = connector_classes if connector_classes is not None else discover_connectors()
        for connector_id, cls in classes.items():
            try:
                instance = cls()
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "connector_instantiation_failed",
                    extra={"connector_id": connector_id, "error": str(exc)},
                )
                continue

            enabled = True
            try:
                await instance.authenticate()
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "connector_auth_failed",
                    extra={"connector_id": connector_id, "error": str(exc)},
                )
                enabled = False
            self._records[connector_id] = ConnectorRecord(
                connector_id=connector_id,
                cls=cls,
                instance=instance,
                enabled=enabled,
            )

    def get(self, connector_id: str) -> BaseConnector | None:
        """Return the enabled connector instance for *connector_id*, or ``None``.

        Returns ``None`` when the connector is unknown or disabled.
        """
        record = self._records.get(connector_id)
        return record.instance if (record and record.enabled) else None

    def register(
        self,
        connector_id: str,
        instance: BaseConnector,
        enabled: bool = True,
    ) -> None:
        """Register a single pre-built, pre-authenticated connector instance.

        Unlike :meth:`load` (entry-point discovery, one shared instance per
        connector *type*), this lets a caller register connectors under any
        key — e.g. the indexing pipeline registers one instance per
        knowledge-source UUID, since each source has its own Vault
        credentials and scope (repo/project/space).
        """
        self._records[connector_id] = ConnectorRecord(
            connector_id=connector_id,
            cls=type(instance),
            instance=instance,
            enabled=enabled,
        )

    def all_enabled(self) -> list[BaseConnector]:
        """Return all connector instances whose ``enabled`` flag is ``True``."""
        return [r.instance for r in self._records.values() if r.enabled]

    def set_health(
        self,
        connector_id: str,
        healthy: bool,
        checked_at: datetime,
    ) -> None:
        """Update health state; called by ``ConnectorHealthPoller`` (TASK-US021-03).

        An unhealthy connector is immediately disabled to prevent further use.
        """
        if record := self._records.get(connector_id):
            record.last_health = healthy
            record.last_checked = checked_at
            if not healthy:
                record.enabled = False

    def records(self) -> list[ConnectorRecord]:
        """Return a snapshot of all ``ConnectorRecord`` entries."""
        return list(self._records.values())
