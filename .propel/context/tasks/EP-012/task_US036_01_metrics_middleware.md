# TASK-US036-01 — RED Metrics Registry, `MetricsMiddleware`, and `/metrics` Endpoint

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US036-01 |
| User Story | US-036 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Define the four core RED metrics (AC-2), register them in a shared `MetricsRegistry`, implement a Starlette `MetricsMiddleware` that instruments every FastAPI service with per-request counter/histogram/gauge increments using the required four label dimensions (AC-3), and expose the `/metrics` endpoint in Prometheus text format (AC-1). All services include this middleware via a shared `src/observability/metrics` package so the implementation is written once.

## Implementation Details

**Technology:** Python 3.11+, `prometheus-client>=0.20`, FastAPI/Starlette, `pydantic-settings`

**File locations:**
- `src/observability/metrics/registry.py` — `MetricsRegistry` (singletons for all 4 metrics)
- `src/observability/metrics/middleware.py` — `MetricsMiddleware` (Starlette `BaseHTTPMiddleware`)
- `src/observability/metrics/endpoint.py` — `/metrics` FastAPI router
- `src/observability/metrics/settings.py` — `MetricsSettings` (service name config)
- `src/main.py` — mount middleware and router (each service's entrypoint does this)

---

### `MetricsSettings`

```python
# src/observability/metrics/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class MetricsSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix = "METRICS_",
        env_file   = ".env",
    )

    service_name: str = "contextiq-api"   # overridden per-service via METRICS_SERVICE_NAME
    enabled:      bool = True
```

---

### `MetricsRegistry`

```python
# src/observability/metrics/registry.py
from __future__ import annotations
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, REGISTRY

# Use the default global registry so prometheus_client's generate_latest() works.
# Per-service label values are injected at request time, not at registration time.

# AC-2 + AC-3: all four metrics with all four required label dimensions.
_LABEL_NAMES = ["service", "endpoint", "intent_type", "tenant_id"]

contextiq_requests_total = Counter(
    "contextiq_requests_total",
    "Total number of HTTP requests handled.",
    _LABEL_NAMES,
)

contextiq_request_duration_seconds = Histogram(
    "contextiq_request_duration_seconds",
    "HTTP request latency in seconds.",
    _LABEL_NAMES,
    # Buckets tuned for ContextIQ latency profile; p95 alert threshold is 3 s
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
)

contextiq_errors_total = Counter(
    "contextiq_errors_total",
    "Total number of requests that resulted in a 5xx error.",
    _LABEL_NAMES,
)

contextiq_active_requests = Gauge(
    "contextiq_active_requests",
    "Number of requests currently being processed.",
    _LABEL_NAMES,
)
```

---

### `MetricsMiddleware`

```python
# src/observability/metrics/middleware.py
from __future__ import annotations
import time
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests        import Request
from starlette.responses       import Response

from src.observability.metrics.registry import (
    contextiq_requests_total,
    contextiq_request_duration_seconds,
    contextiq_errors_total,
    contextiq_active_requests,
)
from src.observability.metrics.settings import MetricsSettings

logger = logging.getLogger(__name__)

# Paths that must not be instrumented to avoid label cardinality explosion
_SKIP_PATHS = frozenset({"/metrics", "/healthz", "/readyz", "/favicon.ico"})


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that records all four RED metrics for every HTTP request.

    Label resolution:
    - service      → MetricsSettings.service_name (from METRICS_SERVICE_NAME env var)
    - endpoint     → request.url.path (path template, not raw URL, to avoid cardinality)
    - intent_type  → request.state.intent_type (set by upstream JWT/routing middleware)
    - tenant_id    → request.state.tenant_id   (set by upstream JWT middleware)
    """

    def __init__(self, app, settings: MetricsSettings | None = None) -> None:
        super().__init__(app)
        self._settings = settings or MetricsSettings()

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip infrastructure endpoints to avoid polluting metric cardinality
        if path in _SKIP_PATHS or not self._settings.enabled:
            return await call_next(request)

        # Normalise path template: replace path params with placeholders
        endpoint   = _normalise_path(path)
        intent     = getattr(request.state, "intent_type", "unknown")
        tenant_id  = getattr(request.state, "tenant_id",   "unknown")
        service    = self._settings.service_name

        labels = {
            "service":     service,
            "endpoint":    endpoint,
            "intent_type": intent,
            "tenant_id":   tenant_id,
        }

        contextiq_active_requests.labels(**labels).inc()
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            contextiq_errors_total.labels(**labels).inc()
            raise
        finally:
            elapsed = time.perf_counter() - start
            contextiq_active_requests.labels(**labels).dec()
            contextiq_request_duration_seconds.labels(**labels).observe(elapsed)

        contextiq_requests_total.labels(**labels).inc()
        if response.status_code >= 500:
            contextiq_errors_total.labels(**labels).inc()

        return response


def _normalise_path(path: str) -> str:
    """
    Coerce URL paths with IDs to a low-cardinality template.
    e.g. /v1/traces/3fa85f64-5717-4562-b3fc-2c963f66afa6 → /v1/traces/{id}

    Replaces UUID segments and pure-integer segments with placeholders.
    """
    import re
    path = re.sub(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "{id}",
        path,
    )
    path = re.sub(r"/\d+", "/{id}", path)
    return path
```

---

### `/metrics` endpoint

```python
# src/observability/metrics/endpoint.py
from fastapi  import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

router = APIRouter(tags=["Observability"])


@router.get(
    "/metrics",
    response_class = PlainTextResponse,
    include_in_schema = False,   # exclude from OpenAPI docs
    summary = "Prometheus metrics scrape endpoint.",
)
async def metrics_endpoint() -> PlainTextResponse:
    """
    AC-1: Exposes all registered metrics in Prometheus text exposition format.
    Scraped by the Kubernetes ServiceMonitor on port 8080 path /metrics.
    """
    return PlainTextResponse(
        content      = generate_latest().decode("utf-8"),
        media_type   = CONTENT_TYPE_LATEST,
    )
```

---

### Service entrypoint integration

Each FastAPI service registers the middleware and router in `main.py`:

```python
# src/main.py  (pattern — each service applies the same block)
from fastapi import FastAPI
from src.observability.metrics.middleware import MetricsMiddleware
from src.observability.metrics.endpoint  import router as metrics_router
from src.observability.metrics.settings  import MetricsSettings

app = FastAPI()

# Mount BEFORE other middleware so instrumentation wraps all request handling
app.add_middleware(MetricsMiddleware, settings=MetricsSettings())
app.include_router(metrics_router)
```

## Acceptance Criteria

- [ ] `GET /metrics` returns HTTP 200 with `Content-Type: text/plain; version=0.0.4` (AC-1)
- [ ] Response body contains all four metric names: `contextiq_requests_total`, `contextiq_request_duration_seconds`, `contextiq_errors_total`, `contextiq_active_requests` (AC-2)
- [ ] Each metric's `HELP` line is present and each sample line contains all four label names: `service`, `endpoint`, `intent_type`, `tenant_id` (AC-3)
- [ ] A 5xx response increments `contextiq_errors_total` and `contextiq_requests_total` (AC-2)
- [ ] `contextiq_active_requests` is decremented after request completion (no gauge leak)
- [ ] `_normalise_path()` replaces UUID and integer path segments — confirmed in unit tests

## Dependencies

- `prometheus-client>=0.20` (already in project per EP-010 conventions)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
