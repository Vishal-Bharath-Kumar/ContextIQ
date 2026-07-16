"""
OpenTelemetry provider setup and tracer factory.

TASK-US001-05: Instrument MCP Connections with OpenTelemetry Spans.

Usage
-----
Call ``setup_telemetry(settings)`` once during application lifespan startup.
Obtain a tracer via ``get_tracer()``.  Both functions are safe to call even
when the OTel SDK is absent or the collector is unreachable — failures are
logged as warnings and a no-op tracer is returned.

Transport context
-----------------
``set_transport_context(transport)`` / ``get_transport_context()`` share the
active MCP transport type (``"sse"`` | ``"websocket"``) across the call stack
via a ``contextvars.ContextVar``.  The middleware sets it on connection open;
handlers read it for span attributes.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer

logger = logging.getLogger(__name__)

_SERVICE_NAME = "contextiq-gateway"
_TRACER_NAME = "contextiq.gateway"

# Module-level sentinel; replaced by real provider in setup_telemetry().
_provider_initialised: bool = False

# Per-request transport type — set by ConnectionTracingMiddleware.
_transport_ctx: ContextVar[str] = ContextVar("mcp_transport", default="unknown")


def set_transport_context(transport: str) -> None:
    """Set the active MCP transport type in the current context."""
    _transport_ctx.set(transport)


def get_transport_context() -> str:
    """Return the active MCP transport type, or ``'unknown'`` if not set."""
    return _transport_ctx.get()


def setup_telemetry(otel_endpoint: str, sampler_arg: float = 1.0) -> None:
    """
    Initialise the OTel TracerProvider and attach the OTLP gRPC exporter.

    Must be called inside the FastAPI application lifespan so that the
    provider is torn down cleanly on shutdown.  If initialisation fails
    (e.g. the collector is unreachable at startup) a warning is logged and
    the gateway continues with a no-op tracer — it does **not** crash.

    Parameters
    ----------
    otel_endpoint:
        OTLP gRPC endpoint, e.g. ``http://jaeger-collector:4317``.
    sampler_arg:
        TraceIdRatio sampler probability in [0.0, 1.0].  Maps to
        ``OTEL_TRACES_SAMPLER_ARG``.  Default 1.0 = 100 % sampling.
    """
    global _provider_initialised  # noqa: PLW0603

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        sampler = TraceIdRatioBased(sampler_arg)
        resource = Resource({SERVICE_NAME: _SERVICE_NAME})
        provider = TracerProvider(resource=resource, sampler=sampler)

        exporter = OTLPSpanExporter(endpoint=otel_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        _provider_initialised = True

        # Auto-instrument Redis commands so GET/SET appear as child spans.
        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor  # type: ignore[import-untyped]

            RedisInstrumentor().instrument()
        except Exception:  # noqa: BLE001
            logger.warning("RedisInstrumentor setup failed — Redis spans will not be exported.")

        logger.info(
            "OTel tracer provider initialised: endpoint=%r sampler_arg=%s",
            otel_endpoint,
            sampler_arg,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "OTel initialisation failed — continuing with no-op tracer. "
            "Traces will NOT be exported.",
            exc_info=True,
        )


def get_tracer() -> Tracer:
    """
    Return the module-level OTel tracer for the gateway.

    Returns a no-op tracer if the SDK is not installed or ``setup_telemetry``
    was not called / failed.
    """
    try:
        from opentelemetry import trace

        return trace.get_tracer(_TRACER_NAME)
    except ImportError:  # pragma: no cover — only absent in stripped envs
        from opentelemetry.trace import NoOpTracer  # type: ignore[attr-defined]

        return NoOpTracer()
