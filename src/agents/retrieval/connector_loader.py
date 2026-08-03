"""ConnectorLoader — populates ConnectorRegistry from PostgreSQL config at startup.

TASK-US007-04: Connector Registry: Active Connector Selection from Execution Plan.

Provides:
* :data:`CONNECTOR_CLASS_MAP` — connector type string → (connector_cls, config_cls)
* :class:`ConnectorLoader` — queries DB, instantiates connectors, calls authenticate()
* :func:`health_check_loop` — 30 s background task that marks unhealthy connectors
* :func:`config_change_listener` — Redis pub/sub watcher for dynamic re-registration
"""
from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.agents.retrieval.connector_registry import ConnectorRegistry
from src.connector_sdk.base import BaseConnector
from src.connector_sdk.schemas.health import HealthStatus
from src.connectors.confluence.config import ConfluenceConnectorConfig
from src.connectors.confluence.connector import ConfluenceConnector
from src.connectors.github.config import GitHubConnectorConfig
from src.connectors.github.connector import GitHubConnector
from src.connectors.grafana.config import GrafanaConnectorConfig
from src.connectors.grafana.connector import GrafanaConnector
from src.connectors.jira.config import JiraConnectorConfig
from src.connectors.jira.connector import JiraConnector
from src.data.models.connector_config import ConnectorConfig

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connector type → (connector class, config class) mapping
# ---------------------------------------------------------------------------

CONNECTOR_CLASS_MAP: dict[str, tuple[type[BaseConnector], type]] = {
    "github": (GitHubConnector, GitHubConnectorConfig),
    "confluence": (ConfluenceConnector, ConfluenceConnectorConfig),
    "jira": (JiraConnector, JiraConnectorConfig),
    "grafana": (GrafanaConnector, GrafanaConnectorConfig),
}

# Redis channel published by Admin API (TASK-US002-02 pattern)
_CONFIG_CHANGE_CHANNEL = "contextiq:connector_config:changed"

# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------


async def health_check_loop(registry: ConnectorRegistry) -> None:
    """Poll every registered connector every 30 s; update health in registry.

    Per AC: an unresponsive connector becomes unhealthy within 35 s
    (30 s sleep + 5 s per-connector timeout).  Connectors that raise or timeout
    are marked unhealthy and silently excluded from dispatch.

    Must be started as a background ``asyncio.Task`` in the FastAPI lifespan::

        task = asyncio.create_task(health_check_loop(registry))
    """
    while True:
        # Snapshot keys to avoid mutation during iteration
        for source_id, connector in list(registry._connectors.items()):
            try:
                status: HealthStatus = await asyncio.wait_for(
                    connector.health_check(), timeout=5.0
                )
                registry.set_health(source_id, status.healthy)
            except Exception:
                registry.set_health(source_id, False)
                _logger.warning(
                    "connector_health_check_failed",
                    extra={"source_id": source_id},
                )
        await asyncio.sleep(30)


async def config_change_listener(
    registry: ConnectorRegistry,
    redis_client: aioredis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Subscribe to ``contextiq:connector_config:changed`` for dynamic re-registration.

    Message format: JSON object with a ``"name"`` key identifying the connector
    config row that changed.  On receipt, :meth:`ConnectorLoader.reload_connector`
    is called to pull the latest DB state without a service restart.

    Args:
        registry:        Shared ``ConnectorRegistry`` instance to mutate.
        redis_client:    Dedicated Redis client for pub/sub (must not be shared).
        session_factory: Async SQLAlchemy session factory (``async_sessionmaker``).
    """
    loader = ConnectorLoader()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(_CONFIG_CHANGE_CHANNEL)
    _logger.info("connector_config_listener_started", extra={"channel": _CONFIG_CHANGE_CHANNEL})

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            payload: dict[str, str] = json.loads(message["data"])
            connector_name: str = payload["name"]
        except (KeyError, json.JSONDecodeError, TypeError) as exc:
            _logger.warning(
                "connector_config_change_invalid_payload",
                extra={"error": str(exc)},
            )
            continue

        async with session_factory() as db_session:
            await loader.reload_connector(registry, db_session, connector_name)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class ConnectorLoader:
    """Queries the ``connector_config`` table and populates a :class:`ConnectorRegistry`.

    Connectors whose ``enabled`` flag is ``False`` are skipped.  Connectors
    whose ``authenticate()`` raises are logged but do not abort the rest of
    the load — the service remains operational for all other connectors.
    """

    async def load(
        self,
        registry: ConnectorRegistry,
        db_session: AsyncSession,
    ) -> None:
        """Instantiate all active connectors and register them.

        Args:
            registry:   Registry to populate.
            db_session: SQLAlchemy async session for the primary DB.
        """
        result = await db_session.execute(
            select(ConnectorConfig).where(ConnectorConfig.enabled.is_(True))
        )
        configs: list[ConnectorConfig] = list(result.scalars().all())

        for config in configs:
            await self._instantiate_and_register(registry, config)

    async def reload_connector(
        self,
        registry: ConnectorRegistry,
        db_session: AsyncSession,
        connector_name: str,
    ) -> None:
        """Reload a single connector by name — used for dynamic re-registration.

        If the connector config no longer exists or is disabled, it is
        unregistered from the registry.

        Args:
            registry:        Target registry to update.
            db_session:      SQLAlchemy async session for the primary DB.
            connector_name:  Value of ``ConnectorConfig.name`` to reload.
        """
        result = await db_session.execute(
            select(ConnectorConfig)
            .where(ConnectorConfig.name == connector_name)
            .where(ConnectorConfig.enabled.is_(True))
        )
        config = result.scalars().first()

        if config is None:
            registry.unregister(connector_name)
            _logger.info(
                "connector_deregistered_on_disable",
                extra={"connector_name": connector_name},
            )
            return

        await self._instantiate_and_register(registry, config)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _instantiate_and_register(
        self,
        registry: ConnectorRegistry,
        config: ConnectorConfig,
    ) -> None:
        """Instantiate connector from *config* and register it.

        On auth failure the connector is not registered; other connectors
        continue to load normally.
        """
        connector_type = config.connector_type.value

        if connector_type not in CONNECTOR_CLASS_MAP:
            _logger.warning(
                "connector_type_not_in_class_map",
                extra={"connector_type": connector_type, "connector_name": config.name},
            )
            return

        connector_cls, config_cls = CONNECTOR_CLASS_MAP[connector_type]
        try:
            connector_config = config_cls(**(config.config or {}))
            connector = connector_cls(config=connector_config)
            await connector.authenticate()
            registry.register(config.name, connector)
        except Exception as exc:
            _logger.error(
                "connector_instantiation_failed",
                extra={
                    "connector_name": config.name,
                    "connector_type": connector_type,
                    "error": str(exc),
                },
            )
