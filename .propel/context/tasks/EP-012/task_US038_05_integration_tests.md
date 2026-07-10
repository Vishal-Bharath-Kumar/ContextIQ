# TASK-US038-05 — Integration Tests Covering All 7 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US038-05 |
| User Story | US-038 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Write the test suite covering all 7 US-038 acceptance criteria using `InMemorySpanExporter` — no live Jaeger or OTLP endpoint required in CI. Tests verify: MCP tool call root span carries the `request_id`-derived trace ID (AC-1), each of the five pipeline nodes produces a named child span (AC-2), connector `fetch()` produces a child span with `connector_id` (AC-3), required span attributes are present (AC-4), the OTLP exporter is configured with the correct endpoint (AC-5), trace is retrievable within 5 s SLA via `BatchSpanProcessor` flush timing (AC-6), and `setup_tracing()` is idempotent (AC-7).

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `opentelemetry-sdk` `InMemorySpanExporter`, `SimpleSpanProcessor` (synchronous, no batching delay in tests)

**File locations:**
- `tests/observability/test_root_span.py` — AC-1, AC-7
- `tests/observability/test_node_spans.py` — AC-2, AC-4
- `tests/observability/test_connector_span.py` — AC-3, AC-4
- `tests/observability/test_otel_setup.py` — AC-5, AC-6, AC-7
- `tests/observability/conftest.py` — shared `InMemorySpanExporter` fixture

---

### Shared OTel test fixtures

```python
# tests/observability/conftest.py  (extend existing file)
import pytest
import uuid
from opentelemetry                  import trace
from opentelemetry.sdk.trace        import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.resources    import Resource, SERVICE_NAME


@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture(autouse=True)
def otel_provider(span_exporter: InMemorySpanExporter):
    """
    Replace the global TracerProvider with an in-memory one for the duration of each test.
    SimpleSpanProcessor (synchronous) ensures spans are available immediately after node call.
    """
    resource  = Resource.create({SERVICE_NAME: "test"})
    provider  = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    original = trace.get_tracer_provider()
    trace.set_tracer_provider(provider)

    # Reset module-level singleton so setup_tracing() may be re-tested
    import src.observability.tracing.setup as setup_mod
    setup_mod._TRACING_INITIALIZED = False

    yield provider

    trace.set_tracer_provider(original)
    span_exporter.clear()
```

---

### AC-1 — Root span trace ID equals `request_id.hex`

```python
# tests/observability/test_root_span.py
import uuid
from src.observability.tracing.root_span import start_root_span, _uuid_to_trace_id


def test_uuid_to_trace_id_strips_hyphens():
    """AC-1: UUID maps to its 128-bit integer — same as parsing hex without hyphens."""
    uid = uuid.UUID("3fa85f64-5717-4562-b3fc-2c963f66afa6")
    assert _uuid_to_trace_id(uid) == int("3fa85f6457174562b3fc2c963f66afa6", 16)


def test_root_span_trace_id_equals_request_id_hex(span_exporter):
    """AC-1: root span trace_id in hex equals request_id without hyphens."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        pass

    spans = span_exporter.get_finished_spans()
    assert len(spans) >= 1

    root = spans[0]
    trace_id_hex = f"{root.context.trace_id:032x}"
    assert trace_id_hex == req_id.hex, (
        f"Expected trace_id {req_id.hex}, got {trace_id_hex}"
    )


def test_root_span_has_request_id_attribute(span_exporter):
    """AC-1: root span carries request_id as a span attribute."""
    req_id = uuid.uuid4()
    with start_root_span(req_id, operation="mcp.test"):
        pass

    spans = span_exporter.get_finished_spans()
    attrs = spans[0].attributes
    assert attrs.get("request_id") == str(req_id)


def test_root_span_context_stored_in_rsc(span_exporter):
    """AC-1: RootSpanContext.trace_id_hex matches the started span's trace_id."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        assert rsc.trace_id_hex == req_id.hex
```

---

### AC-2 — Five pipeline nodes each produce a named child span

```python
# tests/observability/test_node_spans.py
import uuid
from src.observability.tracing.root_span  import start_root_span
from src.observability.tracing.node_span  import otel_node_span
from src.agents.state import AgentState


@otel_node_span("intent.classify")
async def _fake_intent(state: dict) -> dict:
    return {**state, "intent": "technical_support"}


@otel_node_span("retrieval.hybrid_search")
async def _fake_retrieval(state: dict) -> dict:
    return state


@otel_node_span("compression.context_window")
async def _fake_compression(state: dict) -> dict:
    return {**state, "compression_tokens_after": 400}


@otel_node_span("governance.pii_scan")
async def _fake_governance(state: dict) -> dict:
    return state


@otel_node_span("routing.model_select")
async def _fake_routing(state: dict) -> dict:
    return {**state, "model_selected": "gpt-4o"}


async def test_five_node_spans_created(span_exporter):
    """AC-2: each of the five pipeline nodes creates exactly one named child span."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        state = {"_otel_ctx": rsc, "request_id": str(req_id), "tenant_id": "acme"}
        state = await _fake_intent(state)
        state = await _fake_retrieval(state)
        state = await _fake_compression(state)
        state = await _fake_governance(state)
        state = await _fake_routing(state)

    span_names = [s.name for s in span_exporter.get_finished_spans()]
    assert "intent.classify"          in span_names
    assert "retrieval.hybrid_search"  in span_names
    assert "compression.context_window" in span_names
    assert "governance.pii_scan"      in span_names
    assert "routing.model_select"     in span_names


async def test_node_spans_share_root_trace_id(span_exporter):
    """AC-2: all node spans share the root span's trace_id."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        state = {"_otel_ctx": rsc, "request_id": str(req_id)}
        await _fake_intent(state)
        await _fake_retrieval(state)

    spans = span_exporter.get_finished_spans()
    trace_ids = {f"{s.context.trace_id:032x}" for s in spans}
    assert trace_ids == {req_id.hex}, f"Multiple trace IDs found: {trace_ids}"
```

---

### AC-4 — Required span attributes

```python
async def test_intent_type_attribute_propagated(span_exporter):
    """AC-4: intent_type attribute is set on node spans after intent classification."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        state = {"_otel_ctx": rsc}
        state = await _fake_intent(state)
        await _fake_retrieval(state)

    retrieval_span = next(
        s for s in span_exporter.get_finished_spans()
        if s.name == "retrieval.hybrid_search"
    )
    # intent_type was set in _set_pre_attributes for the retrieval span
    assert retrieval_span.attributes.get("intent_type") == "technical_support"


async def test_model_id_attribute_set_after_routing(span_exporter):
    """AC-4: model_id attribute is set on the routing span."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        state = {"_otel_ctx": rsc}
        await _fake_routing(state)

    routing_span = next(
        s for s in span_exporter.get_finished_spans()
        if s.name == "routing.model_select"
    )
    assert routing_span.attributes.get("model_id") == "gpt-4o"


async def test_token_count_set_after_compression(span_exporter):
    """AC-4: token_count attribute reflects post-compression count."""
    req_id = uuid.uuid4()
    with start_root_span(req_id) as rsc:
        state = {"_otel_ctx": rsc}
        await _fake_compression(state)

    comp_span = next(
        s for s in span_exporter.get_finished_spans()
        if s.name == "compression.context_window"
    )
    assert comp_span.attributes.get("token_count") == 400
```

---

### AC-3 + AC-4 — Connector span with `connector_id`

```python
# tests/observability/test_connector_span.py
import uuid
from src.observability.tracing.root_span    import start_root_span
from src.observability.tracing.connector_span import connector_span


class _FakeConnector:
    connector_id:   str = "confluence-prod"
    source_id:      str = "src-abc123"
    connector_type: str = "confluence"
    _otel_ctx       = None
    _request_id:    str = ""

    @connector_span
    async def fetch(self, query: str) -> list[dict]:
        return [{"text": "result"}]


async def test_connector_span_created(span_exporter):
    """AC-3: fetch() call creates a child span named connector.{connector_id}.fetch."""
    req_id    = uuid.uuid4()
    connector = _FakeConnector()

    with start_root_span(req_id) as rsc:
        connector._otel_ctx   = rsc
        connector._request_id = str(req_id)
        await connector.fetch("test query")

    span_names = [s.name for s in span_exporter.get_finished_spans()]
    assert "connector.confluence-prod.fetch" in span_names


async def test_connector_span_has_required_attributes(span_exporter):
    """AC-4: connector span has connector_id and source_id attributes."""
    req_id    = uuid.uuid4()
    connector = _FakeConnector()

    with start_root_span(req_id) as rsc:
        connector._otel_ctx = rsc
        await connector.fetch("test")

    conn_span = next(
        s for s in span_exporter.get_finished_spans()
        if "connector" in s.name
    )
    assert conn_span.attributes.get("connector_id") == "confluence-prod"
    assert conn_span.attributes.get("source_id")    == "src-abc123"


async def test_connector_span_no_otel_ctx_does_not_raise(span_exporter):
    """AC-3: connector without _otel_ctx runs without instrumentation — no error."""
    connector = _FakeConnector()
    connector._otel_ctx = None
    result = await connector.fetch("test")
    assert result == [{"text": "result"}]
```

---

### AC-5, AC-6, AC-7 — OTel setup configuration tests

```python
# tests/observability/test_otel_setup.py
import pytest


def test_setup_tracing_is_idempotent(span_exporter):
    """AC-7: calling setup_tracing() twice does not create a second provider."""
    from opentelemetry import trace
    from src.observability.tracing.setup import setup_tracing, TracingSettings

    settings = TracingSettings(enabled=False)   # disabled to avoid real gRPC
    p1 = setup_tracing(settings)
    p2 = setup_tracing(settings)

    # Second call returns existing provider — no duplication
    assert trace.get_tracer_provider() is trace.get_tracer_provider()


def test_otlp_exporter_endpoint_is_configurable(monkeypatch):
    """AC-5: OTLPSpanExporter endpoint read from OTEL_EXPORTER_OTLP_ENDPOINT."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger-test:4317")
    from src.observability.tracing.setup import TracingSettings
    settings = TracingSettings()
    assert settings.exporter_otlp_endpoint == "http://jaeger-test:4317"


def test_bsp_schedule_delay_is_1000ms():
    """AC-6: 1 s flush delay ensures traces reach Jaeger within the 5 s SLA."""
    from src.observability.tracing.setup import TracingSettings
    settings = TracingSettings()
    assert settings.bsp_schedule_delay_millis == 1000


def test_propagator_includes_w3c_tracecontext():
    """AC-1: W3C TraceContext propagator is registered globally."""
    from src.observability.tracing.setup import setup_tracing, TracingSettings
    from opentelemetry.propagate import get_global_textmap
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    setup_tracing(TracingSettings(enabled=False))
    propagators = get_global_textmap()
    # CompositePropagator wraps the individual propagators
    names = [type(p).__name__ for p in getattr(propagators, "_propagators", [])]
    assert "TraceContextTextMapPropagator" in names


def test_node_span_graceful_when_no_otel_ctx():
    """AC-7: decorator is a no-op when TracerProvider is the NoOpTracerProvider."""
    import asyncio
    from src.observability.tracing.node_span import otel_node_span

    @otel_node_span()
    async def _node(state): return {**state, "ran": True}

    result = asyncio.get_event_loop().run_until_complete(_node({"_otel_ctx": None}))
    assert result["ran"] is True
```

## Acceptance Criteria

- [ ] `test_root_span_trace_id_equals_request_id_hex` — trace ID in hex == `request_id.hex` (AC-1)
- [ ] `test_five_node_spans_created` — all five node span names present (AC-2)
- [ ] `test_node_spans_share_root_trace_id` — all child spans share the root trace ID (AC-2)
- [ ] `test_intent_type_attribute_propagated` and `test_model_id_attribute_set_after_routing` — required AC-4 attributes confirmed
- [ ] `test_connector_span_created` — connector span name is `connector.{id}.fetch` (AC-3)
- [ ] `test_connector_span_has_required_attributes` — `connector_id` and `source_id` confirmed (AC-4)
- [ ] `test_connector_span_no_otel_ctx_does_not_raise` — graceful no-op (AC-3)
- [ ] `test_otlp_exporter_endpoint_is_configurable` — env var override works (AC-5)
- [ ] `test_bsp_schedule_delay_is_1000ms` — 1 s delay documented (AC-6)
- [ ] `test_setup_tracing_is_idempotent` — no duplicate provider (AC-7)

## Dependencies

- TASK-US038-01 (`setup_tracing()`, `TracingSettings`)
- TASK-US038-02 (`start_root_span()`, `RootSpanContext`, `_uuid_to_trace_id`)
- TASK-US038-03 (`otel_node_span` decorator)
- TASK-US038-04 (`connector_span` decorator)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests pass with `InMemorySpanExporter` — no live Jaeger or OTLP endpoint in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
