"""
ContextIQ Connector SDK — public API surface.

TASK-US021-01: BaseConnector Abstract Class and Core SDK Data Models.
TASK-US021-02: Entry-Point Auto-Discovery and ConnectorRegistry.

Import from here in all connector implementations:

    from src.connector_sdk import BaseConnector, ConnectorQuery, ConnectorResult
"""
from src.connector_sdk.base import BaseConnector
from src.connector_sdk.discovery import discover_connectors
from src.connector_sdk.exceptions import ConnectorAuthError
from src.connector_sdk.registry import ConnectorRecord, ConnectorRegistry
from src.connector_sdk.schemas.health import HealthStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata
from src.connector_sdk.schemas.sync import SyncResult

__all__ = [
    "BaseConnector",
    "ConnectorAuthError",
    "ConnectorQuery",
    "ConnectorRecord",
    "ConnectorRegistry",
    "ConnectorResult",
    "ResultMetadata",
    "SyncResult",
    "HealthStatus",
    "discover_connectors",
]
