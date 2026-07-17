from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from src.observability.metrics.registry import (
    contextiq_active_requests,
    contextiq_errors_total,
    contextiq_request_duration_seconds,
    contextiq_requests_total,
)
from src.observability.metrics.settings import MetricsSettings

logger = logging.getLogger(__name__)

# Paths that must not be instrumented to avoid label cardinality explosion
_SKIP_PATHS = frozenset({"/metrics", "/healthz", "/readyz", "/favicon.ico"})

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_INT_SEGMENT_RE = re.compile(r"/\d+")


def _normalise_path(path: str) -> str:
    """
    Coerce URL paths with IDs to a low-cardinality template.

    e.g. /v1/traces/3fa85f64-5717-4562-b3fc-2c963f66afa6 → /v1/traces/{id}

    Replaces UUID segments and pure-integer segments with placeholders.
    """
    path = _UUID_RE.sub("{id}", path)
    path = _INT_SEGMENT_RE.sub("/{id}", path)
    return path


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that records all four RED metrics for every HTTP request.

    Label resolution:
    - service      → MetricsSettings.service_name (from METRICS_SERVICE_NAME env var)
    - endpoint     → request.url.path (path template, not raw URL, to avoid cardinality)
    - intent_type  → request.state.intent_type (set by upstream JWT/routing middleware)
    - tenant_id    → request.state.tenant_id   (set by upstream JWT middleware)
    """

    def __init__(self, app: ASGIApp, settings: MetricsSettings | None = None) -> None:
        super().__init__(app)
        self._settings = settings or MetricsSettings()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path

        # Skip infrastructure endpoints to avoid polluting metric cardinality
        if path in _SKIP_PATHS or not self._settings.enabled:
            return await call_next(request)

        endpoint = _normalise_path(path)
        intent = getattr(request.state, "intent_type", "unknown")
        tenant_id = getattr(request.state, "tenant_id", "unknown")
        service = self._settings.service_name

        labels = {
            "service": service,
            "endpoint": endpoint,
            "intent_type": intent,
            "tenant_id": tenant_id,
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
