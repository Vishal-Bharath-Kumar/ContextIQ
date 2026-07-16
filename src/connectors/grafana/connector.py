"""
GrafanaConnector — BaseConnector implementation for Grafana.

TASK-US024-01: Vault Auth, GrafanaConnectorConfig, and authenticate().
TASK-US024-03: fetch(), health_check() implementation.

This module contains the connector with ``authenticate()`` wired to
``GrafanaTokenProvider`` and ``_auth_headers()`` generating Bearer auth
using the service account token.
"""
from __future__ import annotations

import asyncio
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
from src.connectors.grafana.annotation_client import GrafanaAnnotationClient
from src.connectors.grafana.auth import GrafanaCredential, GrafanaTokenProvider
from src.connectors.grafana.config import GrafanaConnectorConfig
from src.events.producer import get_kafka_producer


class GrafanaConnector(BaseConnector):
    """
    Connector for Grafana.

    Call ``authenticate()`` before any other method.  Credentials are cached
    in memory and never written to logs, state, or PostgreSQL.
    """

    def __init__(
        self,
        config: GrafanaConnectorConfig | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        self._config = config or GrafanaConnectorConfig()
        self._session = session          # injected for sync; None in fetch-only usage
        self._token_provider = GrafanaTokenProvider(self._config)
        self._credential: GrafanaCredential | None = None  # set by authenticate()

    async def authenticate(self) -> None:
        """
        Acquire a Grafana service account token from Vault and cache it for
        subsequent API calls.

        Raises:
            ConnectorAuthError: if the connector is disabled via config, or
                when the Vault request fails or the secret is missing the
                ``"token"`` key.
        """
        if not self._config.enabled:
            raise ConnectorAuthError("GrafanaConnector is disabled via config")
        self._credential = await self._token_provider.get_credential()

    def _auth_headers(self) -> dict[str, str]:
        """
        Return HTTP headers for Grafana API requests.

        Grafana: ``Authorization: Bearer <service-account-token>``

        Raises:
            ConnectorAuthError: if ``authenticate()`` has not been called.
        """
        if self._credential is None:
            raise ConnectorAuthError("authenticate() has not been called")
        return {"Authorization": f"Bearer {self._credential.token}", "Accept": "application/json"}

    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        """Fetch Grafana annotations/alerts matching *query* within 3 s (AC-6)."""
        return await asyncio.wait_for(self._fetch_inner(query), timeout=3.0)

    async def _fetch_inner(self, query: ConnectorQuery) -> list[ConnectorResult]:
        client = GrafanaAnnotationClient(self._config)
        annotations, alerts = await client.fetch_annotations_and_alerts(
            auth_headers=self._auth_headers(),
            max_results=query.max_results,
        )
        now = datetime.now(tz=UTC)
        results: list[ConnectorResult] = []

        for ann in annotations:
            results.append(ConnectorResult(
                source_id=f"grafana:annotation:{ann.annotation_id}",
                content=f"{ann.alert_name}: {ann.message}",
                metadata=ResultMetadata(
                    source_url=f"{self._config.base_url}/d/{ann.dashboard_uid}" if ann.dashboard_uid else None,
                    author=None,
                    last_modified=ann.timestamp,
                    extra={
                        "type": "annotation",
                        "state": ann.state,
                        "dashboard_uid": ann.dashboard_uid or "",
                    },
                ),
                fetched_at=now,
            ))

        for alert in alerts:
            label_str = "; ".join(
                f"{k}={v}" for k, v in alert.labels.items() if k != "alertname"
            )
            results.append(ConnectorResult(
                source_id=f"grafana:alert:{alert.fingerprint}",
                content=f"ALERT {alert.state.upper()} — {alert.alert_name}: {alert.message} ({label_str})",
                metadata=ResultMetadata(
                    source_url=f"{self._config.base_url}/alerting",
                    author=None,
                    last_modified=alert.timestamp,
                    extra={
                        "type": "alert",
                        "state": alert.state,
                        "fingerprint": alert.fingerprint,
                    },
                ),
                fetched_at=now,
            ))

        return results[: query.max_results]

    async def sync(self) -> SyncResult:
        """Incrementally sync Grafana annotations/alerts since the last cursor."""
        sync_store = ConnectorSyncStore(self._session)  # type: ignore[arg-type]
        now = datetime.now(tz=UTC)

        last_sync = await sync_store.get_last_sync_at("grafana")
        if last_sync is None:
            last_sync = now - timedelta(hours=self._config.lookback_hours)

        items_processed = 0
        items_failed = 0
        errors: list[str] = []

        try:
            elapsed_hours = (now - last_sync).total_seconds() / 3600
            # Override lookback_hours to cover the elapsed window without mutating config
            sync_config = self._config.model_copy(
                update={"lookback_hours": max(1, int(elapsed_hours) + 1)}
            )
            client = GrafanaAnnotationClient(sync_config)
            annotations, alerts = await client.fetch_annotations_and_alerts(
                auth_headers=self._auth_headers(),
                max_results=500,
            )
            items_processed = len(annotations) + len(alerts)
        except Exception as exc:
            items_failed = 1
            errors.append(f"Grafana sync failed: {type(exc).__name__}: {exc}")

        await sync_store.set_last_sync_at("grafana", now)
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
            "connector_id": "grafana",
            "items_processed": items_processed,
            "synced_at": synced_at.isoformat(),
        }
        producer = await get_kafka_producer()
        await producer.send_and_wait(
            "contextiq.source.sync", value=json.dumps(event).encode()
        )

    async def health_check(self) -> HealthStatus:
        """Liveness check against the Grafana /api/health endpoint."""
        now = datetime.now(tz=UTC)
        try:
            if self._credential is None:
                return HealthStatus(healthy=False, message="Not authenticated", checked_at=now)
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._config.base_url}/api/health",
                    headers=self._auth_headers(),
                )
            if resp.status_code == 200 and resp.json().get("database") == "ok":
                return HealthStatus(healthy=True, message="Grafana healthy", checked_at=now)
            return HealthStatus(
                healthy=False,
                message=f"Grafana /api/health: {resp.text[:150]}",
                checked_at=now,
            )
        except Exception as exc:
            return HealthStatus(
                healthy=False,
                message=f"{type(exc).__name__}: {str(exc)[:150]}",
                checked_at=now,
            )
