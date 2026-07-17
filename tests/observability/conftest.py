from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from opentelemetry import trace

from src.observability.cost.schemas import CompressionRecord, LLMCallRecord
from src.observability.metrics.endpoint import router as metrics_router
from src.observability.metrics.middleware import MetricsMiddleware
from src.observability.metrics.settings import MetricsSettings

# ---------------------------------------------------------------------------
# Shared constants for cost / Langfuse tests (TASK-US037-05)
# ---------------------------------------------------------------------------

REQUEST_ID = uuid.uuid4()
TENANT_ID = "acme"
USER_ID = "user-abc123"
TEAM_ID = "platform-eng"

SAMPLE_LLM_RECORD = LLMCallRecord(
    request_id=REQUEST_ID,
    tenant_id=TENANT_ID,
    model_id="gpt-4o",
    prompt_tokens=512,
    completion_tokens=128,
    cost_usd=0.00480,
    user_id=USER_ID,
    team_id=TEAM_ID,
    intent_type="technical_support",
    timestamp=datetime.now(tz=timezone.utc),
)

SAMPLE_COMPRESSION_RECORD = CompressionRecord(
    request_id=REQUEST_ID,
    tenant_id=TENANT_ID,
    user_id=USER_ID,
    team_id=TEAM_ID,
    intent_type="technical_support",
    timestamp=datetime.now(tz=timezone.utc),
    tokens_before_compression=800,
    tokens_after_compression=400,
)


@pytest.fixture()
def mock_langfuse() -> MagicMock:
    """Patch Langfuse SDK so no real HTTP calls are made."""
    with patch("src.observability.cost.recorder.Langfuse") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


@pytest.fixture
def test_app():
    """Minimal FastAPI app with MetricsMiddleware and /metrics endpoint."""
    app = FastAPI()
    app.add_middleware(
        MetricsMiddleware,
        settings=MetricsSettings(service_name="test-service", enabled=True),
    )
    app.include_router(metrics_router)

    @app.get("/v1/items/{item_id}")
    async def get_item(item_id: str):
        return {"id": item_id}

    @app.get("/v1/fail")
    async def fail():
        raise HTTPException(status_code=500, detail="Simulated error")

    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Shared OTel tracing fixtures (TASK-US038-05)
# ---------------------------------------------------------------------------

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME


@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture(autouse=True)
def otel_provider(span_exporter: InMemorySpanExporter):
    """
    Replace the global TracerProvider with an in-memory one for the duration of each test.
    SimpleSpanProcessor (synchronous) ensures spans are available immediately after node call.
    """
    import opentelemetry.trace as _trace_mod

    resource = Resource.create({SERVICE_NAME: "test"})
    provider = SdkTracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    # This version of opentelemetry-api guards set_tracer_provider with a Once object.
    # Reset both the guard and the stored provider so set_tracer_provider works per-test.
    _trace_mod._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    _trace_mod._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    trace.set_tracer_provider(provider)

    # Reset module-level singleton so setup_tracing() may be re-tested
    import src.observability.tracing.setup as setup_mod
    setup_mod._TRACING_INITIALIZED = False

    # Re-initialise tracer singletons in source modules so they pick up the new provider
    import src.observability.tracing.root_span as root_span_mod
    import src.observability.tracing.node_span as node_span_mod
    import src.observability.tracing.connector_span as connector_span_mod
    root_span_mod._TRACER = trace.get_tracer(root_span_mod.__name__)
    node_span_mod._TRACER = trace.get_tracer(node_span_mod.__name__)
    connector_span_mod._TRACER = trace.get_tracer(connector_span_mod.__name__)

    yield provider

    # Tear down: reset for next test
    _trace_mod._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    _trace_mod._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    span_exporter.clear()
