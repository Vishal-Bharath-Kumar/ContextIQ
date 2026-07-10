# TASK-US024-03 — `GrafanaConnector.fetch()`, Annotations + Alert Client, and `health_check()`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US024-03 |
| User Story | US-024 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `GrafanaAnnotationClient` (fetches dashboard annotations and active alert state via the Grafana HTTP API), `GrafanaConnector.fetch()` (maps results to `ConnectorResult`), and `GrafanaConnector.health_check()` (probes `/api/health`). Results include alert name, state, message, and timestamp. `fetch()` must complete within 3 seconds.

## Implementation Details

**Technology:** Python 3.11+, `httpx[asyncio]>=0.27`, `asyncio`

**File locations:**
- `src/connectors/grafana/annotation_client.py` — `GrafanaAnnotationClient`, `GrafanaAnnotationItem`, `GrafanaAlertItem`
- `src/connectors/grafana/connector.py` — `GrafanaConnector.fetch()`, `health_check()` (extend skeleton)
- `tests/connectors/grafana/test_grafana_fetch.py`

**Grafana API endpoints used:**

| Data | Endpoint | Notes |
|---|---|---|
| Dashboard annotations | `GET /api/annotations` | Filter by `from` (epoch ms), `type=annotation` |
| Active alerts | `GET /api/alertmanager/grafana/api/v2/alerts` | Grafana-managed Alertmanager; returns firing alerts |
| Health probe | `GET /api/health` | Returns `{"database":"ok"}` when healthy |

**`GrafanaAnnotationItem` and `GrafanaAlertItem`:**

```python
# src/connectors/grafana/annotation_client.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class GrafanaAnnotationItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    annotation_id: int
    dashboard_uid: str | None
    alert_name:    str       # "text" field or panelId label
    state:         str       # "alerting" | "ok" | "no_data" | "pending"
    message:       str       # annotation "text"; ≤ 1 000 chars
    timestamp:     datetime

class GrafanaAlertItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    fingerprint:  str
    alert_name:   str        # labels["alertname"]
    state:        str        # status.state: "firing" | "resolved"
    message:      str        # annotations["message"] or annotations["summary"]
    timestamp:    datetime   # startsAt
    labels:       dict[str, str]
```

**`GrafanaAnnotationClient`:**

```python
# src/connectors/grafana/annotation_client.py
import asyncio, httpx
from datetime import datetime, timezone, timedelta
from src.connectors.grafana.config import GrafanaConnectorConfig

class GrafanaAnnotationClient:
    def __init__(self, config: GrafanaConnectorConfig) -> None:
        self._config = config

    async def fetch_annotations_and_alerts(
        self,
        auth_headers: dict[str, str],
        max_results:  int = 100,
    ) -> tuple[list[GrafanaAnnotationItem], list[GrafanaAlertItem]]:
        """Fetch both annotations and active alerts concurrently."""
        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            ann_task   = self._fetch_annotations(client, auth_headers, max_results)
            alert_task = self._fetch_active_alerts(client, auth_headers)
            annotations, alerts = await asyncio.gather(ann_task, alert_task, return_exceptions=True)

        # Degrade gracefully: return empty list for any failed source
        if isinstance(annotations, Exception):
            annotations = []
        if isinstance(alerts, Exception):
            alerts = []
        return annotations, alerts

    async def _fetch_annotations(
        self,
        client:       httpx.AsyncClient,
        auth_headers: dict[str, str],
        max_results:  int,
    ) -> list[GrafanaAnnotationItem]:
        from_epoch_ms = int(
            (datetime.now(tz=timezone.utc) - timedelta(hours=self._config.lookback_hours))
            .timestamp() * 1000
        )
        params: dict = {"from": from_epoch_ms, "type": "annotation", "limit": min(max_results, 100)}
        if self._config.dashboard_uids:
            params["dashboardUID"] = self._config.dashboard_uids[0]   # API accepts one UID per call

        resp = await client.get(
            f"{self._config.base_url}/api/annotations",
            params=params, headers=auth_headers,
        )
        resp.raise_for_status()
        return [self._parse_annotation(r) for r in resp.json()[:max_results]]

    async def _fetch_active_alerts(
        self,
        client:       httpx.AsyncClient,
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
        import dateutil.parser
        ts = datetime.fromtimestamp(r.get("time", 0) / 1000, tz=timezone.utc)
        return GrafanaAnnotationItem(
            annotation_id = r.get("id", 0),
            dashboard_uid = r.get("dashboardUID"),
            alert_name    = r.get("text") or r.get("panelId", "unknown"),
            state         = r.get("newState", "unknown"),
            message       = str(r.get("text", ""))[:1000],
            timestamp     = ts,
        )

    @staticmethod
    def _parse_alert(r: dict) -> GrafanaAlertItem:
        labels  = r.get("labels", {})
        ann     = r.get("annotations", {})
        message = ann.get("message") or ann.get("summary") or ann.get("description", "")
        import dateutil.parser
        starts_at = dateutil.parser.isoparse(r.get("startsAt", "1970-01-01T00:00:00Z"))
        return GrafanaAlertItem(
            fingerprint = r.get("fingerprint", ""),
            alert_name  = labels.get("alertname", "unknown"),
            state       = r.get("status", {}).get("state", "unknown"),
            message     = str(message)[:1000],
            timestamp   = starts_at,
            labels      = {k: v for k, v in labels.items()},
        )
```

**`GrafanaConnector.fetch()` and `health_check()`:**

```python
# src/connectors/grafana/connector.py  — extend existing class
import asyncio
from datetime import datetime, timezone
from src.connector_sdk.schemas.query  import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata
from src.connector_sdk.schemas.health import HealthStatus
from src.connectors.grafana.annotation_client import GrafanaAnnotationClient

    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        return await asyncio.wait_for(self._fetch_inner(query), timeout=3.0)  # US-024 AC-6

    async def _fetch_inner(self, query: ConnectorQuery) -> list[ConnectorResult]:
        client = GrafanaAnnotationClient(self._config)
        annotations, alerts = await client.fetch_annotations_and_alerts(
            auth_headers = self._auth_headers(),
            max_results  = query.max_results,
        )
        now     = datetime.now(tz=timezone.utc)
        results: list[ConnectorResult] = []

        for ann in annotations:
            results.append(ConnectorResult(
                source_id  = f"grafana:annotation:{ann.annotation_id}",
                content    = f"{ann.alert_name}: {ann.message}",
                metadata   = ResultMetadata(
                    source_url    = f"{self._config.base_url}/d/{ann.dashboard_uid}" if ann.dashboard_uid else None,
                    author        = None,
                    last_modified = ann.timestamp,
                    extra         = {"type": "annotation", "state": ann.state,
                                     "dashboard_uid": ann.dashboard_uid or ""},
                ),
                fetched_at = now,
            ))

        for alert in alerts:
            label_str = "; ".join(f"{k}={v}" for k, v in alert.labels.items() if k != "alertname")
            results.append(ConnectorResult(
                source_id  = f"grafana:alert:{alert.fingerprint}",
                content    = f"ALERT {alert.state.upper()} — {alert.alert_name}: {alert.message} ({label_str})",
                metadata   = ResultMetadata(
                    source_url    = f"{self._config.base_url}/alerting",
                    author        = None,
                    last_modified = alert.timestamp,
                    extra         = {"type": "alert", "state": alert.state,
                                     "fingerprint": alert.fingerprint},
                ),
                fetched_at = now,
            ))

        return results[:query.max_results]

    async def health_check(self) -> HealthStatus:
        now = datetime.now(tz=timezone.utc)
        try:
            if self._credential is None:
                return HealthStatus(healthy=False, message="Not authenticated", checked_at=now)
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._config.base_url}/api/health",
                    headers=self._auth_headers(),
                )
            if resp.status_code == 200 and resp.json().get("database") == "ok":
                return HealthStatus(healthy=True, message="Grafana healthy", checked_at=now)
            return HealthStatus(healthy=False, message=f"Grafana /api/health: {resp.text[:150]}", checked_at=now)
        except Exception as exc:
            return HealthStatus(healthy=False, message=f"{type(exc).__name__}: {str(exc)[:150]}", checked_at=now)
```

**Concurrent annotation + alert fetch:**

`asyncio.gather(ann_task, alert_task, return_exceptions=True)` fetches both sources in parallel. If the Alertmanager endpoint is unavailable (e.g. Grafana without managed alerts), alerts degrade to `[]` without blocking annotation results.

## Acceptance Criteria

- [ ] `fetch()` returns `ConnectorResult` items for both annotations and active alerts
- [ ] Annotation `source_id` matches `grafana:annotation:{id}`; alert matches `grafana:alert:{fingerprint}`
- [ ] `metadata.extra["type"]` is `"annotation"` or `"alert"` respectively
- [ ] Alertmanager fetch failure returns empty alerts list; annotation results are still returned
- [ ] `fetch()` raises `asyncio.TimeoutError` when total response exceeds 3 s (mocked)
- [ ] `health_check()` returns `healthy=True` when `/api/health` returns `{"database":"ok"}`
- [ ] `health_check()` does not raise on HTTP 401 or connection error

## Dependencies

- TASK-US024-01 (`GrafanaConnector` skeleton, `_auth_headers()`, `GrafanaConnectorConfig`)
- TASK-US021-01 (`ConnectorQuery`, `ConnectorResult`, `ResultMetadata`, `HealthStatus`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests use `respx`; alert degradation path tested
- [ ] `mypy --strict` passes; no `ruff` lint errors
