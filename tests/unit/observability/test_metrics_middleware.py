"""
Unit tests for TASK-US036-01: RED Metrics Registry, MetricsMiddleware, and /metrics endpoint.

Coverage targets:
  - MetricsSettings: env-var precedence, defaults
  - _normalise_path: UUID and integer segment replacement
  - MetricsMiddleware: counter/histogram/gauge increments, skip paths, 5xx error tracking
  - /metrics endpoint: HTTP 200, correct Content-Type, all four metric names present
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Isolated registry fixture — prevents cross-test pollution from the global
# prometheus_client REGISTRY which is a module-level singleton.
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_registry() -> CollectorRegistry:
    """Return a fresh CollectorRegistry scoped to a single test."""
    return CollectorRegistry()


@pytest.fixture()
def isolated_metrics(
    isolated_registry: CollectorRegistry,
) -> tuple[Counter, Histogram, Counter, Gauge]:
    """Return fresh metric objects backed by the isolated registry."""
    label_names = ["service", "endpoint", "intent_type", "tenant_id"]
    requests_total = Counter(
        "contextiq_requests_total",
        "Total HTTP requests.",
        label_names,
        registry=isolated_registry,
    )
    duration = Histogram(
        "contextiq_request_duration_seconds",
        "Request latency in seconds.",
        label_names,
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
        registry=isolated_registry,
    )
    errors_total = Counter(
        "contextiq_errors_total",
        "Total 5xx error requests.",
        label_names,
        registry=isolated_registry,
    )
    active_requests = Gauge(
        "contextiq_active_requests",
        "Requests currently in flight.",
        label_names,
        registry=isolated_registry,
    )
    return requests_total, duration, errors_total, active_requests


# ---------------------------------------------------------------------------
# MetricsSettings
# ---------------------------------------------------------------------------

class TestMetricsSettings:
    def test_defaults(self) -> None:
        from src.observability.metrics.settings import MetricsSettings

        s = MetricsSettings()
        assert s.service_name == "contextiq-api"
        assert s.enabled is True

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METRICS_SERVICE_NAME", "my-service")
        monkeypatch.setenv("METRICS_ENABLED", "false")

        from src.observability.metrics.settings import MetricsSettings

        s = MetricsSettings()
        assert s.service_name == "my-service"
        assert s.enabled is False


# ---------------------------------------------------------------------------
# _normalise_path
# ---------------------------------------------------------------------------

class TestNormalisePath:
    def test_uuid_replaced(self) -> None:
        from src.observability.metrics.middleware import _normalise_path

        result = _normalise_path("/v1/traces/3fa85f64-5717-4562-b3fc-2c963f66afa6")
        assert result == "/v1/traces/{id}"

    def test_integer_segment_replaced(self) -> None:
        from src.observability.metrics.middleware import _normalise_path

        result = _normalise_path("/api/users/42/profile")
        assert result == "/api/users/{id}/profile"

    def test_no_replacement_for_plain_path(self) -> None:
        from src.observability.metrics.middleware import _normalise_path

        result = _normalise_path("/api/v1/health")
        assert result == "/api/v1/health"

    def test_multiple_uuid_segments_replaced(self) -> None:
        from src.observability.metrics.middleware import _normalise_path

        result = _normalise_path(
            "/v1/a/3fa85f64-5717-4562-b3fc-2c963f66afa6/b/3fa85f64-5717-4562-b3fc-2c963f66afb7"
        )
        assert result == "/v1/a/{id}/b/{id}"

    def test_multiple_int_segments_replaced(self) -> None:
        from src.observability.metrics.middleware import _normalise_path

        result = _normalise_path("/orgs/10/repos/99")
        assert result == "/orgs/{id}/repos/{id}"


# ---------------------------------------------------------------------------
# MetricsMiddleware — helpers
# ---------------------------------------------------------------------------


class TestMetricsMiddleware:
    def test_request_increments_requests_total(
        self,
        isolated_metrics: tuple[Counter, Histogram, Counter, Gauge],
        isolated_registry: CollectorRegistry,
    ) -> None:
        from unittest.mock import patch

        from src.observability.metrics.middleware import MetricsMiddleware
        from src.observability.metrics.settings import MetricsSettings

        requests_total, duration, errors_total, active_requests = isolated_metrics
        settings = MetricsSettings(service_name="test-svc")

        app = FastAPI()
        app.add_middleware(MetricsMiddleware, settings=settings)

        @app.get("/ping")
        async def ping() -> dict[str, Any]:
            return {"pong": True}

        client = TestClient(app, raise_server_exceptions=False)

        with (
            patch("src.observability.metrics.middleware.contextiq_requests_total", requests_total),
            patch(
                "src.observability.metrics.middleware.contextiq_request_duration_seconds",
                duration,
            ),
            patch("src.observability.metrics.middleware.contextiq_errors_total", errors_total),
            patch(
                "src.observability.metrics.middleware.contextiq_active_requests", active_requests
            ),
        ):
            client.get("/ping")

        labels = {
            "service": "test-svc",
            "endpoint": "/ping",
            "intent_type": "unknown",
            "tenant_id": "unknown",
        }
        assert requests_total.labels(**labels)._value.get() == 1.0

    def test_5xx_increments_errors_total(
        self,
        isolated_metrics: tuple[Counter, Histogram, Counter, Gauge],
        isolated_registry: CollectorRegistry,
    ) -> None:
        from unittest.mock import patch

        from fastapi import Response

        from src.observability.metrics.middleware import MetricsMiddleware
        from src.observability.metrics.settings import MetricsSettings

        requests_total, duration, errors_total, active_requests = isolated_metrics
        settings = MetricsSettings(service_name="test-svc")

        app = FastAPI()
        app.add_middleware(MetricsMiddleware, settings=settings)

        @app.get("/fail")
        async def fail() -> Response:
            return Response(status_code=500)

        client = TestClient(app, raise_server_exceptions=False)

        with (
            patch("src.observability.metrics.middleware.contextiq_requests_total", requests_total),
            patch(
                "src.observability.metrics.middleware.contextiq_request_duration_seconds",
                duration,
            ),
            patch("src.observability.metrics.middleware.contextiq_errors_total", errors_total),
            patch(
                "src.observability.metrics.middleware.contextiq_active_requests", active_requests
            ),
        ):
            client.get("/fail")

        labels = {
            "service": "test-svc",
            "endpoint": "/fail",
            "intent_type": "unknown",
            "tenant_id": "unknown",
        }
        assert errors_total.labels(**labels)._value.get() == 1.0

    def test_active_requests_gauge_returns_to_zero(
        self,
        isolated_metrics: tuple[Counter, Histogram, Counter, Gauge],
        isolated_registry: CollectorRegistry,
    ) -> None:
        from unittest.mock import patch

        from src.observability.metrics.middleware import MetricsMiddleware
        from src.observability.metrics.settings import MetricsSettings

        requests_total, duration, errors_total, active_requests = isolated_metrics
        settings = MetricsSettings(service_name="test-svc")

        app = FastAPI()
        app.add_middleware(MetricsMiddleware, settings=settings)

        @app.get("/slow")
        async def slow() -> dict[str, Any]:
            return {"done": True}

        client = TestClient(app, raise_server_exceptions=False)

        with (
            patch("src.observability.metrics.middleware.contextiq_requests_total", requests_total),
            patch(
                "src.observability.metrics.middleware.contextiq_request_duration_seconds",
                duration,
            ),
            patch("src.observability.metrics.middleware.contextiq_errors_total", errors_total),
            patch(
                "src.observability.metrics.middleware.contextiq_active_requests", active_requests
            ),
        ):
            client.get("/slow")

        labels = {
            "service": "test-svc",
            "endpoint": "/slow",
            "intent_type": "unknown",
            "tenant_id": "unknown",
        }
        # Gauge must return to 0 after request completes (no leak)
        assert active_requests.labels(**labels)._value.get() == 0.0

    def test_skip_paths_not_instrumented(
        self,
        isolated_metrics: tuple[Counter, Histogram, Counter, Gauge],
        isolated_registry: CollectorRegistry,
    ) -> None:
        from unittest.mock import patch

        from src.observability.metrics.middleware import MetricsMiddleware
        from src.observability.metrics.settings import MetricsSettings

        requests_total, duration, errors_total, active_requests = isolated_metrics
        settings = MetricsSettings(service_name="test-svc")

        app = FastAPI()
        app.add_middleware(MetricsMiddleware, settings=settings)

        @app.get("/healthz")
        async def healthz() -> dict[str, Any]:
            return {"status": "ok"}

        client = TestClient(app, raise_server_exceptions=False)

        with (
            patch("src.observability.metrics.middleware.contextiq_requests_total", requests_total),
            patch(
                "src.observability.metrics.middleware.contextiq_request_duration_seconds",
                duration,
            ),
            patch("src.observability.metrics.middleware.contextiq_errors_total", errors_total),
            patch(
                "src.observability.metrics.middleware.contextiq_active_requests", active_requests
            ),
        ):
            client.get("/healthz")

        # No label combinations should have been created
        result = isolated_registry.get_sample_value(
            "contextiq_requests_total",
            {"service": "test-svc", "endpoint": "/healthz", "intent_type": "unknown", "tenant_id": "unknown"},
        )
        assert result is None

    def test_disabled_middleware_skips_instrumentation(
        self,
        isolated_metrics: tuple[Counter, Histogram, Counter, Gauge],
        isolated_registry: CollectorRegistry,
    ) -> None:
        from unittest.mock import patch

        from src.observability.metrics.middleware import MetricsMiddleware
        from src.observability.metrics.settings import MetricsSettings

        requests_total, duration, errors_total, active_requests = isolated_metrics
        settings = MetricsSettings(service_name="test-svc", enabled=False)

        app = FastAPI()
        app.add_middleware(MetricsMiddleware, settings=settings)

        @app.get("/any")
        async def any_route() -> dict[str, Any]:
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)

        with (
            patch("src.observability.metrics.middleware.contextiq_requests_total", requests_total),
            patch(
                "src.observability.metrics.middleware.contextiq_request_duration_seconds",
                duration,
            ),
            patch("src.observability.metrics.middleware.contextiq_errors_total", errors_total),
            patch(
                "src.observability.metrics.middleware.contextiq_active_requests", active_requests
            ),
        ):
            client.get("/any")

        result = isolated_registry.get_sample_value(
            "contextiq_requests_total",
            {"service": "test-svc", "endpoint": "/any", "intent_type": "unknown", "tenant_id": "unknown"},
        )
        assert result is None

    def test_duration_histogram_observed(
        self,
        isolated_metrics: tuple[Counter, Histogram, Counter, Gauge],
        isolated_registry: CollectorRegistry,
    ) -> None:
        from unittest.mock import patch

        from src.observability.metrics.middleware import MetricsMiddleware
        from src.observability.metrics.settings import MetricsSettings

        requests_total, duration, errors_total, active_requests = isolated_metrics
        settings = MetricsSettings(service_name="test-svc")

        app = FastAPI()
        app.add_middleware(MetricsMiddleware, settings=settings)

        @app.get("/timed")
        async def timed() -> dict[str, Any]:
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)

        with (
            patch("src.observability.metrics.middleware.contextiq_requests_total", requests_total),
            patch(
                "src.observability.metrics.middleware.contextiq_request_duration_seconds",
                duration,
            ),
            patch("src.observability.metrics.middleware.contextiq_errors_total", errors_total),
            patch(
                "src.observability.metrics.middleware.contextiq_active_requests", active_requests
            ),
        ):
            client.get("/timed")

        labels = {
            "service": "test-svc",
            "endpoint": "/timed",
            "intent_type": "unknown",
            "tenant_id": "unknown",
        }
        count = isolated_registry.get_sample_value(
            "contextiq_request_duration_seconds_count", labels
        )
        assert count == 1.0


# ---------------------------------------------------------------------------
# /metrics endpoint (endpoint.py)
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    def test_returns_200(self) -> None:
        from src.observability.metrics.endpoint import router

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_content_type_is_prometheus_text(self) -> None:
        from src.observability.metrics.endpoint import router

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/metrics")
        assert "text/plain" in response.headers["content-type"]

    def test_response_contains_all_four_metric_names(self) -> None:
        # Import registry to ensure global metrics are registered before scrape
        import src.observability.metrics.registry  # noqa: F401
        from src.observability.metrics.endpoint import router

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)
        body = client.get("/metrics").text
        assert "contextiq_requests_total" in body
        assert "contextiq_request_duration_seconds" in body
        assert "contextiq_errors_total" in body
        assert "contextiq_active_requests" in body

    def test_response_contains_help_lines(self) -> None:
        import src.observability.metrics.registry  # noqa: F401
        from src.observability.metrics.endpoint import router

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)
        body = client.get("/metrics").text
        assert "# HELP contextiq_requests_total" in body
        assert "# HELP contextiq_request_duration_seconds" in body
        assert "# HELP contextiq_errors_total" in body
        assert "# HELP contextiq_active_requests" in body
