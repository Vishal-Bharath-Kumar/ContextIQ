"""
EchoConnector — minimal reference implementation of BaseConnector.

Echoes the query text back as a single ConnectorResult.
No external I/O; safe to run in CI and local dev without credentials.
"""
from __future__ import annotations

from datetime import UTC, datetime

from src.connector_sdk.base import BaseConnector
from src.connector_sdk.schemas.health import HealthStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata
from src.connector_sdk.schemas.sync import SyncResult


class EchoConnector(BaseConnector):
    """Returns the query text as a result; always healthy; no credentials required."""

    async def authenticate(self) -> None:
        # No credentials needed for the echo connector
        pass

    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        return [
            ConnectorResult(
                source_id=f"echo:{hash(query.query) & 0xFFFFFF:06x}",
                content=f"Echo: {query.query}",
                metadata=ResultMetadata(source_url=None, author="echo-connector"),
                fetched_at=datetime.now(tz=UTC),
            )
        ]

    async def sync(self) -> SyncResult:
        return SyncResult(
            items_processed=0,
            items_failed=0,
            last_sync_at=datetime.now(tz=UTC),
        )

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            healthy=True,
            message="EchoConnector is always healthy",
            checked_at=datetime.now(tz=UTC),
        )
