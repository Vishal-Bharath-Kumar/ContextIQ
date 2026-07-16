"""
BaseConnector — abstract base class for all ContextIQ connectors.

TASK-US021-01: BaseConnector Abstract Class and Core SDK Data Models.

All first-party and third-party connectors must subclass BaseConnector and
implement the four abstract methods below.  Methods are async-first;
synchronous I/O must be wrapped in ``asyncio.to_thread()``.

Subclassing contract
--------------------
* ``authenticate()`` — acquire/cache credentials; raise ConnectorAuthError on failure.
* ``fetch()``        — return items matching query within 2 s for ≤ 50 results (NFR-008).
* ``sync()``         — incremental sync; emit DR-005 StateTransitionEvent on completion.
* ``health_check()`` — never raise; catch all errors and return HealthStatus(healthy=False).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.connector_sdk.schemas.health import HealthStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult
from src.connector_sdk.schemas.sync import SyncResult


class BaseConnector(ABC):
    """
    Abstract base class for all ContextIQ connectors.

    Subclasses must implement: ``authenticate``, ``fetch``, ``sync``, ``health_check``.
    All methods are async-first; synchronous connectors must wrap I/O in
    ``asyncio.to_thread()``.
    """

    @abstractmethod
    async def authenticate(self) -> None:
        """
        Acquire and cache credentials for this connector session.

        Raises ``ConnectorAuthError`` on failure.
        Called once at startup and re-called by the health poller on auth expiry.
        """
        ...

    @abstractmethod
    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        """
        Retrieve items matching *query* from the external source.

        Must return within 2 s for ≤ 50 results (NFR-008).
        """
        ...

    @abstractmethod
    async def sync(self) -> SyncResult:
        """
        Perform an incremental sync; fetch only items changed since last sync.

        Emit a DR-005 StateTransitionEvent on completion.
        """
        ...

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """
        Return a :class:`HealthStatus`.

        Must not raise — catch all internal errors and return
        ``HealthStatus(healthy=False, message=str(exc), ...)``.
        Called every 30 s by ConnectorHealthPoller.
        """
        ...
