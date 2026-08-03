# TASK-US001-05 — Instrument MCP Connections with OpenTelemetry Spans

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US001-05 |
| User Story | US-001 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Observability |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Add OpenTelemetry instrumentation to the MCP gateway so that every inbound connection attempt, `initialize` handshake, and transport negotiation emits a traced span with relevant attributes. Spans are exported to the platform Jaeger instance via OTLP gRPC.

## Implementation Details

**Technology:** Python 3.11+, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-instrumentation-fastapi`

**File locations:**
- `src/gateway/telemetry.py` — OTel provider setup and tracer factory
- `src/gateway/main.py` — register `FastAPIInstrumentor` at app startup
- `src/gateway/handlers/initialize.py` — manual span for `initialize` handler
- `src/gateway/middleware/tracing.py` — ASGI span middleware for raw transport connections

**Key implementation steps:**

1. Configure OTel tracer provider in `telemetry.py`:
   ```python
   from opentelemetry import trace
   from opentelemetry.sdk.trace import TracerProvider
   from opentelemetry.sdk.trace.export import BatchSpanProcessor
   from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

   provider = TracerProvider(resource=Resource({SERVICE_NAME: "contextiq-gateway"}))
   exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint)
   provider.add_span_processor(BatchSpanProcessor(exporter))
   trace.set_tracer_provider(provider)
   ```

2. Attach `FastAPIInstrumentor` to the FastAPI app for automatic HTTP span generation:
   ```python
   FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
   ```

3. Add manual span for each `initialize` call:
   ```python
   tracer = trace.get_tracer("contextiq.gateway")

   with tracer.start_as_current_span("mcp.initialize") as span:
       span.set_attribute("mcp.protocol_version", request.protocolVersion)
       span.set_attribute("mcp.client.name", request.clientInfo.name)
       span.set_attribute("mcp.transport", transport_type)  # "sse" | "websocket"
   ```

4. Add span for WebSocket/SSE connection lifecycle:
   - `mcp.connection.open` span on transport connect
   - `mcp.connection.close` span on disconnect with `mcp.session_duration_ms` attribute

5. Environment variable: `OTEL_EXPORTER_OTLP_ENDPOINT` (e.g., `http://jaeger-collector:4317`)

**Key span attributes to capture:**

| Attribute | Value |
|---|---|
| `mcp.transport` | `sse` or `websocket` |
| `mcp.client.name` | from `clientInfo.name` |
| `mcp.protocol_version` | from `initialize` request |
| `http.status_code` | HTTP response code |
| `net.peer.ip` | Client IP (from X-Forwarded-For) |
| `contextiq.circuit_state` | `closed` / `open` / `half_open` |

## Acceptance Criteria

- [ ] Every `initialize` call produces a Jaeger trace with a `mcp.initialize` span containing `mcp.client.name` and `mcp.transport` attributes
- [ ] WebSocket and SSE connection spans are visible as sibling spans under the root HTTP trace
- [ ] OTLP exporter flushes spans to `jaeger-collector:4317` (verified in Jaeger UI)
- [ ] OTel SDK initialization failure (unreachable collector) logs a warning but does not crash the gateway
- [ ] Sampling rate is configurable via `OTEL_TRACES_SAMPLER_ARG` env var (default: `1.0` = 100%)
- [ ] Unit tests mock the tracer and assert span attribute values

## Dependencies

- TASK-US001-01 (FastMCP + FastAPI app instance)
- TASK-US001-03 (`initialize` handler — span added inside handler)
- US-045 (Jaeger deployed to `contextiq-observability` namespace)

## Definition of Done

- [ ] `opentelemetry-instrumentation-fastapi` and `opentelemetry-exporter-otlp-proto-grpc` added to `pyproject.toml`
- [ ] OTel provider initialized in application lifespan (not module-level)
- [ ] Unit tests assert span count and key attributes using `InMemorySpanExporter`
- [ ] Jaeger UI shows `contextiq-gateway` service with `mcp.initialize` spans in staging
- [ ] `OTEL_EXPORTER_OTLP_ENDPOINT` documented in `.env.example`
