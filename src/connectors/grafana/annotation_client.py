"""
GrafanaAnnotationClient — fetches dashboard annotations and active alert state.

TASK-US024-03: GrafanaConnector.fetch(), Annotations + Alert Client, and health_check().

Both sources are fetched concurrently via asyncio.gather().  If either endpoint
fails (e.g. Alertmanager not configured), the failed source degrades to an
empty list without blocking the other.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import BaseModel, ConfigDict

from src.connectors.grafana.config import GrafanaConnectorConfig


class GrafanaAnnotationItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    annotation_id: int
    dashboard_uid: str | None
    alert_name: str       # "text" field or panelId label
    state: str            # "alerting" | "ok" | "no_data" | "pending"
    message: str          # annotation "text"; <= 1 000 chars
    timestamp: datetime


class GrafanaAlertItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    fingerprint: str
    alert_name: str       # labels["alertname"]
    state: str            # status.state: "firing" | "resolved"
    message: str          # annotations["message"] or annotations["summary"]
    timestamp: datetime   # startsAt
    labels: dict[str, str]


class GrafanaAnnotationClient:
    def __init__(self, config: GrafanaConnectorConfig) -> None:
        self._config = config

    async def fetch_annotations_and_alerts(
        self,
        auth_headers: dict[str, str],
        max_results: int = 100,
    ) -> tuple[list[GrafanaAnnotationItem], list[GrafanaAlertItem]]:
        """Fetch both annotations and active alerts concurrently."""
        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            ann_task = self._fetch_annotations(client, auth_headers, max_results)
            alert_task = self._fetch_active_alerts(client, auth_headers)
            annotations, alerts = await asyncio.gather(ann_task, alert_task, return_exceptions=True)

        # Degrade gracefully: return empty list for any failed source
        if isinstance(annotations, Exception):
            annotations = []
        if isinstance(alerts, Exception):
            alerts = []
        return annotations, alerts  # type: ignore[return-value]

    async def _fetch_annotations(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        max_results: int,
    ) -> list[GrafanaAnnotationItem]:
        from_epoch_ms = int(
            (datetime.now(tz=timezone.utc) - timedelta(hours=self._config.lookback_hours))
            .timestamp() * 1000
        )
        params: dict[str, object] = {
            "from": from_epoch_ms,
            "type": "annotation",
            "limit": min(max_results, 100),
        }
        if self._config.dashboard_uids:
            params["dashboardUID"] = self._config.dashboard_uids[0]

        resp = await client.get(
            f"{self._config.base_url}/api/annotations",
            params=params,
            headers=auth_headers,
        )
        resp.raise_for_status()
        return [self._parse_annotation(r) for r in resp.json()[:max_results]]

    async def _fetch_active_alerts(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> list[GrafanaAlertItem]:
        resp = await client.get(
            f"{self._config.base_url}/api/alertmanager/grafana/api/v2/alerts",
            headers=auth_headers,
        )
        resp.raise_for_status()
        return [self._parse_alert(r) for r in resp.json()]

    @staticmethod
    def _parse_annotation(r: dict) -> GrafanaAnnotationItem:
        ts = datetime.fromtimestamp(r.get("time", 0) / 1000, tz=timezone.utc)
        return GrafanaAnnotationItem(
            annotation_id=r.get("id", 0),
            dashboard_uid=r.get("dashboardUID"),
            alert_name=r.get("text") or str(r.get("panelId", "unknown")),
            state=r.get("newState", "unknown"),
            message=str(r.get("text", ""))[:1000],
            timestamp=ts,
        )

    @staticmethod
    def _parse_alert(r: dict) -> GrafanaAlertItem:
        labels = r.get("labels", {})
        ann = r.get("annotations", {})
        message = ann.get("message") or ann.get("summary") or ann.get("description", "")
        starts_at = datetime.fromisoformat(r.get("startsAt", "1970-01-01T00:00:00+00:00"))
        return GrafanaAlertItem(
            fingerprint=r.get("fingerprint", ""),
            alert_name=labels.get("alertname", "unknown"),
            state=r.get("status", {}).get("state", "unknown"),
            message=str(message)[:1000],
            timestamp=starts_at,
            labels={k: v for k, v in labels.items()},
        )
