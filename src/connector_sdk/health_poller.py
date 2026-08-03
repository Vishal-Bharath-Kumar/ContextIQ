"""
ConnectorHealthPoller — background asyncio task that health-checks all
registered connectors every ``interval_s`` seconds (default 30).

TASK-US021-03: ConnectorHealthPoller — 30-Second Background Health Check.

When a connector reports ``healthy=False`` (or raises from ``health_check()``)
it is disabled in :class:`~src.connector_sdk.registry.ConnectorRegistry` and
the ``connector_health_checks_total`` Prometheus counter is incremented with
``status="unhealthy"``.

The poller is started from the FastAPI lifespan and cancelled cleanly on
shutdown via :meth:`ConnectorHealthPoller.stop`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from src.connector_sdk.metrics import connector_health_checks_total, connectors_enabled_gauge
from src.connector_sdk.registry import ConnectorRegistry

_log = logging.getLogger(__name__)

POLL_INTERVAL_S: int = 30  # US-021 AC-4: polled every 30 s


class ConnectorHealthPoller:
    """Background health-check loop for all registered connectors."""

    def __init__(self, registry: ConnectorRegistry, interval_s: int = POLL_INTERVAL_S) -> None:
        self._registry = registry
        self._interval_s = interval_s
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the background polling loop. Idempotent."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop(), name="connector_health_poller")

    def stop(self) -> None:
        """Cancel the polling task. Called from FastAPI lifespan teardown."""
        if self._task and not self._task.done():
            self._task.cancel()

    async def _poll_loop(self) -> None:
        while True:
            await self._poll_once()
            await asyncio.sleep(self._interval_s)

    async def _poll_once(self) -> None:
        """Poll all registered connectors; update registry + metrics."""
        for record in self._registry.records():
            try:
                status = await record.instance.health_check()
            except Exception as exc:  # noqa: BLE001
                # health_check() must not raise — if it does, treat as unhealthy
                _log.error(
                    "health_check_raised",
                    extra={"connector_id": record.connector_id, "error": str(exc)},
                )
                from src.connector_sdk.schemas.health import HealthStatus  # noqa: PLC0415

                status = HealthStatus(
                    healthy=False,
                    message=f"health_check() raised: {exc}",
                    checked_at=datetime.now(tz=UTC),
                )

            label = "healthy" if status.healthy else "unhealthy"
            connector_health_checks_total.labels(
                connector_id=record.connector_id,
                status=label,
            ).inc()

            if not status.healthy:
                _log.warning(
                    "connector_disabled",
                    extra={
                        "connector_id": record.connector_id,
                        "health_message": status.message,
                    },
                )

            self._registry.set_health(
                connector_id=record.connector_id,
                healthy=status.healthy,
                checked_at=status.checked_at,
            )

        # Recompute enabled gauge after all records updated
        connectors_enabled_gauge.set(len(self._registry.all_enabled()))
