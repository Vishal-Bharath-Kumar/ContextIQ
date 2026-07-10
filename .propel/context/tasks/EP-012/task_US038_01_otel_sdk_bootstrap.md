# TASK-US038-01 — OTel SDK Bootstrap: `TracerProvider`, OTLP gRPC Exporter, and `setup_tracing()`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US038-01 |
| User Story | US-038 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement the cross-cutting OTel SDK bootstrap that every ContextIQ service calls once at lifespan startup (AC-7). `setup_tracing()` configures a global `TracerProvider` with a `BatchSpanProcessor` and `OTLPSpanExporter` (gRPC, AC-5), registers W3C `TraceContextTextMapPropagator` + `BaggagePropagator` for distributed context propagation, and installs FastAPI/HTTPX auto-instrumentation. All pipeline nodes and connectors then call `opentelemetry.trace.get_tracer(__name__)` — no per-service setup required (AC-7).

## Implementation Details

**Technology:** Python 3.11+, `opentelemetry-sdk>=1.25`, `opentelemetry-exporter-otlp-proto-grpc>=1.25`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-httpx`, `pydantic-settings`

**File locations:**
- `src/observability/tracing/setup.py` — `setup_tracing()`, `TracingSettings`
- `src/observability/tracing/__init__.py` — re-exports `get_tracer` convenience wrapper
- `src/main.py` — call `setup_tracing()` in lifespan (extend existing startup)

---

### `TracingSettings`

```python
# src/observability/tracing/setup.py
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict


class TracingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix = "OTEL_",
        env_file   = ".env",
    )

    # AC-5: OTLP gRPC endpoint pointing at Jaeger collector
    exporter_otlp_endpoint: str  = "http://jaeger-collector:4317"
    service_name:           str  = "contextiq-api"   # overridden per service
    enabled:                bool = True

    # BatchSpanProcessor tuning — keeps Jaeger retrievability within 5 s (AC-6)
    bsp_max_export_batch_size:  int   = 512
    bsp_schedule_delay_millis:  int   = 1000   # flush every 1 s
    bsp_export_timeout_millis:  int   = 3000
```

---

### `setup_tracing()`

```python
# src/observability/tracing/setup.py  (continued)
from __future__ import annotations
import logging

from opentelemetry                                     import trace
from opentelemetry.sdk.trace                           import TracerProvider
from opentelemetry.sdk.trace.export                    import BatchSpanProcessor
from opentelemetry.sdk.resources                       import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate                           import set_global_textmap
from opentelemetry.propagators.composite               import CompositePropagator
from opentelemetry.trace.propagation.tracecontext      import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation                 import W3CBaggagePropagator

logger = logging.getLogger(__name__)

# Module-level sentinel: prevents double-initialisation when tests import the module
_TRACING_INITIALIZED = False


def setup_tracing(settings: TracingSettings | None = None) -> TracerProvider | None:
    """
    AC-7: Cross-cutting OTel SDK initialisation.

    Called ONCE per service process in the FastAPI lifespan startup handler.
    All services share the same code path — no per-service OTel wiring.

    Returns the configured TracerProvider (or None if tracing is disabled),
    primarily for test injection.
    """
    global _TRACING_INITIALIZED
    if _TRACING_INITIALIZED:
        logger.debug("setup_tracing() already called — skipping re-initialisation.")
        return trace.get_tracer_provider()   # type: ignore[return-value]

    cfg = settings or TracingSettings()

    if not cfg.enabled:
        logger.info("OpenTelemetry tracing disabled (OTEL_ENABLED=false).")
        return None

    # Resource: identifies the service in Jaeger UI
    resource = Resource.create({SERVICE_NAME: cfg.service_name})

    # OTLP gRPC exporter — AC-5
    exporter = OTLPSpanExporter(
        endpoint = cfg.exporter_otlp_endpoint,
        insecure = True,   # TLS terminated at the service mesh; plain gRPC within the cluster
    )

    # BatchSpanProcessor with 1 s flush delay → Jaeger retrievability within 5 s (AC-6)
    processor = BatchSpanProcessor(
        span_exporter            = exporter,
        max_export_batch_size    = cfg.bsp_max_export_batch_size,
        schedule_delay_millis    = cfg.bsp_schedule_delay_millis,
        export_timeout_millis    = cfg.bsp_export_timeout_millis,
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(processor)

    # Register as the global provider so get_tracer(__name__) resolves everywhere
    trace.set_tracer_provider(provider)

    # W3C TraceContext + Baggage propagators (AC-1: `traceparent` header carries trace ID)
    set_global_textmap(CompositePropagator([
        TraceContextTextMapPropagator(),
        W3CBaggagePropagator(),
    ]))

    # Auto-instrumentation for FastAPI and httpx (connectors use httpx)
    _install_auto_instrumentation()

    _TRACING_INITIALIZED = True
    logger.info(
        "OpenTelemetry tracing initialised. service=%s endpoint=%s",
        cfg.service_name, cfg.exporter_otlp_endpoint,
    )
    return provider


def _install_auto_instrumentation() -> None:
    """
    Install OTel auto-instrumentation for FastAPI requests and httpx outbound calls.
    FastAPI instrumentation creates a server span for each HTTP request.
    httpx instrumentation creates a client span for each outbound connector call.
    """
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor().instrument()
    except ImportError:
        logger.warning("opentelemetry-instrumentation-fastapi not installed.")

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except ImportError:
        logger.warning("opentelemetry-instrumentation-httpx not installed.")


def teardown_tracing() -> None:
    """
    Flush and shut down the global TracerProvider.
    Called in the FastAPI lifespan shutdown handler.
    Ensures all pending spans are exported before pod termination (AC-6).
    """
    global _TRACING_INITIALIZED
    provider = trace.get_tracer_provider()
    if hasattr(provider, "shutdown"):
        provider.shutdown()
    _TRACING_INITIALIZED = False
    logger.info("OpenTelemetry tracing shut down.")
```

---

### Convenience wrapper

```python
# src/observability/tracing/__init__.py
from opentelemetry import trace as _otel_trace

def get_tracer(name: str):
    """Thin wrapper so internal modules call get_tracer(__name__) consistently."""
    return _otel_trace.get_tracer(name)
```

---

### Lifespan integration

```python
# src/main.py  (extend existing lifespan — do NOT rewrite)
from contextlib import asynccontextmanager
from src.observability.tracing.setup import setup_tracing, teardown_tracing

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_tracing()          # AC-7: called once at startup
    # … other startup …
    yield
    teardown_tracing()       # flush spans before shutdown
```

## Acceptance Criteria

- [ ] `setup_tracing()` is idempotent — calling it twice does not create a second `TracerProvider` (AC-7)
- [ ] `TracerProvider` is registered as the global provider so any `get_tracer(__name__)` call resolves without an import of `setup_tracing` (AC-7)
- [ ] `OTLPSpanExporter` endpoint is `OTEL_EXPORTER_OTLP_ENDPOINT` (env-configurable, AC-5)
- [ ] `BatchSpanProcessor.schedule_delay_millis = 1000` — spans flushed within 1 s, supporting the 5 s Jaeger retrievability SLA (AC-6)
- [ ] `TraceContextTextMapPropagator` is registered globally — `traceparent` headers on inbound requests propagate trace context
- [ ] `teardown_tracing()` calls `provider.shutdown()` — no span loss on pod termination

## Dependencies

- `opentelemetry-sdk>=1.25`, `opentelemetry-exporter-otlp-proto-grpc>=1.25`
- `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-httpx`

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
