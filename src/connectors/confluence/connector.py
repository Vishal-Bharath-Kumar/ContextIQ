"""
ConfluenceConnector — BaseConnector implementation for Confluence.

TASK-US023-01: ConfluenceConnectorConfig, Vault Token Provider, and authenticate().
TASK-US023-03: fetch() results mapping and plain-text extraction.

This module contains the connector skeleton with ``authenticate()`` wired to
``ConfluenceTokenProvider`` and ``_auth_headers()`` generating the correct
header for Cloud (Basic) or Data Center (Bearer PAT) deployments.
The ``sync()`` and ``health_check()`` methods are stubbed and
will be implemented in subsequent tasks.
"""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.connector_sdk.base import BaseConnector
from src.connector_sdk.exceptions import ConnectorAuthError
from src.connector_sdk.schemas.health import HealthStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata
from src.connector_sdk.schemas.sync import SyncResult
from src.connectors.confluence.auth import ConfluenceCredential, ConfluenceTokenProvider
from src.connectors.confluence.chunker import ConfluencePageChunker
from src.connectors.confluence.config import ConfluenceConnectorConfig, ConfluenceDeploymentType
from src.connectors.confluence.cql_client import ConfluenceCQLClient
from src.connectors.confluence.html_stripper import strip_confluence_storage
from src.connectors.github.sync_store import ConnectorSyncStore
from src.events.producer import get_kafka_producer


class ConfluenceConnector(BaseConnector):
    """
    Connector for Confluence Cloud and Data Center.

    Call ``authenticate()`` before any other method.  Credentials are cached
    in memory and never written to logs, state, or PostgreSQL.
    """

    def __init__(
        self,
        config: ConfluenceConnectorConfig | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        self._config = config or ConfluenceConnectorConfig()
        self._session = session  # injected for sync; None in fetch-only usage
        self._token_provider = ConfluenceTokenProvider(self._config)
        self._credential: ConfluenceCredential | None = None  # set by authenticate()

    async def authenticate(self) -> None:
        """
        Acquire a Confluence token from Vault and cache it for subsequent API calls.

        Re-called by ConnectorHealthPoller on auth expiry.

        Raises:
            ConnectorAuthError: when the Vault request fails or the secret is
                missing the ``"token"`` key.
        """
        self._credential = await self._token_provider.get_credential()

    def _auth_headers(self) -> dict[str, str]:
        """
        Return HTTP headers for Confluence API requests.

        Cloud:       ``Authorization: Basic <base64(email:token)>``
        Data Center: ``Authorization: Bearer <token>``

        Raises:
            ConnectorAuthError: if ``authenticate()`` has not been called.
        """
        if self._credential is None:
            raise ConnectorAuthError("authenticate() has not been called")
        if self._credential.deployment_type == ConfluenceDeploymentType.CLOUD:
            raw = f"{self._credential.email}:{self._credential.token}"
            encoded = base64.b64encode(raw.encode()).decode()
            return {"Authorization": f"Basic {encoded}", "Accept": "application/json"}
        return {"Authorization": f"Bearer {self._credential.token}", "Accept": "application/json"}

    # ------------------------------------------------------------------
    # fetch — TASK-US023-03
    # ------------------------------------------------------------------

    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        """
        Search Confluence and return mapped ConnectorResult items.

        Raises:
            ConnectorAuthError: if ``authenticate()`` has not been called.
            asyncio.TimeoutError: if search + mapping exceeds 2 seconds.
        """
        if self._credential is None:
            raise ConnectorAuthError("authenticate() has not been called")
        return await asyncio.wait_for(
            self._fetch_inner(query),
            timeout=2.0,
        )

    async def _fetch_inner(self, query: ConnectorQuery) -> list[ConnectorResult]:
        cql_client = ConfluenceCQLClient(self._config)
        spaces = (
            list(query.filters["spaces"].split(","))
            if query.filters.get("spaces")
            else self._config.spaces
        )

        items = await cql_client.search(
            query=query.query,
            spaces=spaces,
            auth_headers=self._auth_headers(),
            max_results=query.max_results,
        )

        results: list[ConnectorResult] = []
        for item in items:
            plain_text = strip_confluence_storage(item.body_excerpt)
            results.append(
                ConnectorResult(
                    source_id=f"confluence:{item.space_key}:{item.page_id}",
                    content=plain_text,
                    metadata=ResultMetadata(
                        source_url=item.url,
                        author=item.author,
                        last_modified=item.last_modified,
                        extra={
                            "page_title": item.title,
                            "space_key": item.space_key,
                            "page_id": item.page_id,
                        },
                    ),
                    fetched_at=datetime.now(tz=UTC),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Stubbed methods — to be implemented in subsequent tasks
    # ------------------------------------------------------------------

    async def sync(self) -> SyncResult:
        """
        Incremental sync using a CQL ``lastModified`` filter.

        Fetches pages updated since ``last_sync_at``, chunks them via
        ``ConfluencePageChunker``, persists the new cursor, and emits a
        ``source_sync_completed`` Kafka event.
        """
        sync_store = ConnectorSyncStore(self._session)
        cql_client = ConfluenceCQLClient(self._config)
        chunker = ConfluencePageChunker()
        now = datetime.now(tz=UTC)

        last_sync = await sync_store.get_last_sync_at("confluence")
        if last_sync is None:
            last_sync = now - timedelta(days=self._config.default_days)

        # CQL lastModified filter (ISO-8601 date without time for CQL compatibility)
        since_date = last_sync.strftime("%Y-%m-%d")
        extra_cql = f'lastModified >= "{since_date}"'

        items_processed = 0
        items_failed = 0
        errors: list[str] = []

        try:
            pages = await cql_client.search(
                query="",  # empty query = all pages in spaces matching filter
                spaces=self._config.spaces,
                auth_headers=self._auth_headers(),
                max_results=500,
                extra_cql=extra_cql,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"CQL sync search failed: {type(exc).__name__}: {exc}")
            return SyncResult(
                items_processed=0,
                items_failed=1,
                last_sync_at=now,
                errors=errors,
            )

        for page in pages:
            try:
                plain = strip_confluence_storage(page.body_excerpt)
                chunks = chunker.chunk(page.page_id, plain)
                items_processed += len(chunks)
            except Exception as exc:  # noqa: BLE001
                items_failed += 1
                errors.append(f"{page.page_id}: {type(exc).__name__}: {exc}")

        await sync_store.set_last_sync_at("confluence", now)
        await self._emit_sync_event(items_processed=items_processed, synced_at=now)
        return SyncResult(
            items_processed=items_processed,
            items_failed=items_failed,
            last_sync_at=now,
            errors=errors,
        )

    async def _emit_sync_event(self, items_processed: int, synced_at: datetime) -> None:
        """Publish a ``source_sync_completed`` event to Kafka."""
        event = {
            "event_type": "source_sync_completed",
            "connector_id": "confluence",
            "items_processed": items_processed,
            "synced_at": synced_at.isoformat(),
        }
        producer = await get_kafka_producer()
        await producer.send_and_wait(
            "contextiq.source.sync", value=json.dumps(event).encode()
        )

    async def health_check(self) -> HealthStatus:
        """
        Validate the cached token by calling GET /space (Cloud) or GET /rest/api/space (DC).
        Returns HealthStatus(healthy=False) on any error — must not raise.
        """
        import httpx

        now = datetime.now(tz=UTC)
        try:
            if self._credential is None:
                return HealthStatus(
                    healthy=False,
                    message="Not authenticated; call authenticate() first",
                    checked_at=now,
                )
            path = (
                "/wiki/rest/api/space"
                if self._config.deployment_type == ConfluenceDeploymentType.CLOUD
                else "/rest/api/space"
            )
            url = f"{self._config.base_url.rstrip('/')}{path}"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers=self._auth_headers(), params={"limit": 1})
            if resp.status_code == 200:
                return HealthStatus(
                    healthy=True,
                    message=f"Confluence reachable at {self._config.base_url}",
                    checked_at=now,
                )
            return HealthStatus(
                healthy=False,
                message=f"Confluence /space returned HTTP {resp.status_code}",
                checked_at=now,
            )
        except Exception as exc:
            return HealthStatus(
                healthy=False,
                message=f"{type(exc).__name__}: {str(exc)[:150]}",
                checked_at=now,
            )
