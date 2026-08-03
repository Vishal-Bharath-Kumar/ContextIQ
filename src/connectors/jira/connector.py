"""
JiraConnector — BaseConnector implementation for Jira.

TASK-US024-01: Vault Auth, JiraConnectorConfig, and authenticate().
TASK-US024-02: fetch(), _fetch_inner(), and health_check() implementation.

This module contains the connector with ``authenticate()`` wired to
``JiraTokenProvider`` and ``_auth_headers()`` generating HTTP Basic auth
(base64-encoded email:token) for Jira Cloud.
``fetch()`` delegates to ``JiraSearchClient`` with a 3-second timeout (AC-6).
``health_check()`` probes ``/rest/api/3/myself``.
"""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.connector_sdk.base import BaseConnector
from src.connector_sdk.exceptions import ConnectorAuthError
from src.connector_sdk.schemas.health import HealthStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata
from src.connector_sdk.schemas.sync import SyncResult
from src.connectors.github.sync_store import ConnectorSyncStore
from src.connectors.jira.auth import JiraCredential, JiraTokenProvider
from src.connectors.jira.config import JiraConnectorConfig
from src.connectors.jira.search_client import JiraSearchClient
from src.events.producer import get_kafka_producer


class JiraConnector(BaseConnector):
    """
    Connector for Jira Cloud.

    Call ``authenticate()`` before any other method.  Credentials are cached
    in memory and never written to logs, state, or PostgreSQL.
    """

    def __init__(
        self,
        config: JiraConnectorConfig | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        self._config = config or JiraConnectorConfig()
        self._session = session          # injected for sync; None in fetch-only usage
        self._token_provider = JiraTokenProvider(self._config)
        self._credential: JiraCredential | None = None  # set by authenticate()

    async def authenticate(self) -> None:
        """
        Acquire a Jira token from Vault and cache it for subsequent API calls.

        Raises:
            ConnectorAuthError: if the connector is disabled via config, or
                when the Vault request fails or the secret is missing the
                ``"token"`` key.
        """
        if not self._config.enabled:
            raise ConnectorAuthError("JiraConnector is disabled via config")
        self._credential = await self._token_provider.get_credential()

    def _auth_headers(self) -> dict[str, str]:
        """
        Return HTTP headers for Jira API requests.

        Jira Cloud: ``Authorization: Basic <base64(email:token)>``

        Raises:
            ConnectorAuthError: if ``authenticate()`` has not been called.
        """
        if self._credential is None:
            raise ConnectorAuthError("authenticate() has not been called")
        raw = f"{self._credential.email}:{self._credential.token}"
        encoded = base64.b64encode(raw.encode()).decode()
        return {"Authorization": f"Basic {encoded}", "Accept": "application/json"}

    # ------------------------------------------------------------------
    # Fetch — TASK-US024-02
    # ------------------------------------------------------------------

    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        """Search Jira issues matching *query* within a 3-second timeout (AC-6)."""
        return await asyncio.wait_for(self._fetch_inner(query), timeout=3.0)

    async def _fetch_inner(self, query: ConnectorQuery) -> list[ConnectorResult]:
        client = JiraSearchClient(self._config)
        items = await client.search(
            query=query.query,
            auth_headers=self._auth_headers(),
            filters=query.filters,
            max_results=query.max_results,
        )
        now = datetime.now(tz=UTC)
        return [
            ConnectorResult(
                source_id=f"jira:{item.issue_key}",
                content=f"[{item.issue_key}] {item.summary}\n{item.description}",
                metadata=ResultMetadata(
                    source_url=item.url,
                    author=item.assignee,
                    last_modified=item.updated,
                    extra={
                        "issue_key": item.issue_key,
                        "status": item.status,
                        "priority": item.priority or "None",
                    },
                ),
                fetched_at=now,
            )
            for item in items
        ]

    # ------------------------------------------------------------------
    # Health check — TASK-US024-02
    # ------------------------------------------------------------------

    async def health_check(self) -> HealthStatus:
        """Probe ``/rest/api/3/myself`` to verify Jira connectivity and auth."""
        now = datetime.now(tz=UTC)
        try:
            if self._credential is None:
                return HealthStatus(healthy=False, message="Not authenticated", checked_at=now)
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._config.base_url}/rest/api/3/myself",
                    headers=self._auth_headers(),
                )
            if resp.status_code == 200:
                account_id = resp.json().get("accountId", "unknown")
                return HealthStatus(
                    healthy=True,
                    message=f"Jira authenticated as {account_id}",
                    checked_at=now,
                )
            return HealthStatus(
                healthy=False,
                message=f"Jira /myself returned HTTP {resp.status_code}",
                checked_at=now,
            )
        except Exception as exc:
            return HealthStatus(
                healthy=False,
                message=f"{type(exc).__name__}: {str(exc)[:150]}",
                checked_at=now,
            )

    # ------------------------------------------------------------------
    # Sync — TASK-US024-04
    # ------------------------------------------------------------------

    async def sync(self) -> SyncResult:
        """Incrementally sync Jira issues updated since the last cursor."""
        sync_store = ConnectorSyncStore(self._session)  # type: ignore[arg-type]
        now = datetime.now(tz=UTC)

        last_sync = await sync_store.get_last_sync_at("jira")
        if last_sync is None:
            last_sync = now - timedelta(days=self._config.default_days)

        # JQL date format: "YYYY-MM-DD HH:mm" — Jira does not accept ISO-8601 with 'T' in JQL
        since_str = last_sync.strftime("%Y-%m-%d %H:%M")
        sync_jql = f'updated >= "{since_str}" ORDER BY updated ASC'

        items_processed = 0
        items_failed = 0
        errors: list[str] = []

        try:
            client = JiraSearchClient(self._config)
            issues = await client.search(
                query="",
                auth_headers=self._auth_headers(),
                filters={"_jql_override": sync_jql},
                max_results=500,
            )
            items_processed = len(issues)
        except Exception as exc:
            items_failed = 1
            errors.append(f"Jira sync search failed: {type(exc).__name__}: {exc}")

        await sync_store.set_last_sync_at("jira", now)
        await self._emit_sync_event(items_processed=items_processed, synced_at=now)

        return SyncResult(
            items_processed=items_processed,
            items_failed=items_failed,
            last_sync_at=now,
            errors=errors,
        )

    async def _emit_sync_event(self, items_processed: int, synced_at: datetime) -> None:
        """Publish a source_sync_completed event to the contextiq.source.sync topic."""
        event = {
            "event_type": "source_sync_completed",
            "connector_id": "jira",
            "items_processed": items_processed,
            "synced_at": synced_at.isoformat(),
        }
        producer = await get_kafka_producer()
        await producer.send_and_wait(
            "contextiq.source.sync", value=json.dumps(event).encode()
        )
