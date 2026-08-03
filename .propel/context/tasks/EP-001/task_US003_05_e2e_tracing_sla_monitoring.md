# TASK-US003-05 — End-to-End Correlation ID Tracing and SLA Monitoring

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US003-05 |
| User Story | US-003 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Observability |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Propagate an OTel trace context (W3C `traceparent`) from the MCP gateway through the Agent Worker and all downstream services so that a complete end-to-end trace for each tool call is visible in Jaeger. Also add Prometheus histogram and alerting for the p95 < 3 s latency SLA.

## Implementation Details

**Technology:** Python 3.11+, `opentelemetry-sdk`, `opentelemetry-propagator-b3` / W3C, Prometheus `Histogram`, Grafana

**File locations:**
- `src/gateway/handlers/tools_call.py` — root span creation and `traceparent` injection
- `src/gateway/clients/agent_worker_client.py` — `traceparent` header attachment
- `src/gateway/telemetry.py` — histogram registration
- `tests/gateway/test_tools_call_tracing.py`

**Root span for each tool call:**
```python
with tracer.start_as_current_span(
    "mcp.tools.call",
    kind=trace.SpanKind.SERVER,
) as span:
    span.set_attribute("mcp.tool.name", name)
    span.set_attribute("mcp.request_id", dispatch.request_id)
    span.set_attribute("contextiq.user_id", ctx.user_id)
    # ... dispatch and record result
    span.set_attribute("mcp.tool.success", not is_error)
    span.set_attribute("mcp.tool.duration_ms", elapsed_ms)
```

**W3C `traceparent` propagation to Agent Worker:**
```python
from opentelemetry.propagate import inject

headers: dict[str, str] = {}
inject(headers)    # populates "traceparent" and "tracestate" from current span context
response = await client.post(url, json=payload, headers={**headers, **auth_headers})
```
The Agent Worker reads `traceparent`, creates a child span, and the full trace is stitched together in Jaeger.

**Latency histogram for SLA tracking:**
```python
tool_call_duration = Histogram(
    "contextiq_tool_call_duration_seconds",
    "End-to-end tool call duration from gateway receipt to response",
    ["tool_name", "status"],        # status: success | error | timeout
    buckets=[0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0, 10.0],
)
```
Record at the end of the handler:
```python
tool_call_duration.labels(tool_name=name, status=status).observe(elapsed_seconds)
```

**Prometheus alert rule for SLA breach:**
```yaml
# PrometheusRule resource in Helm chart
- alert: ToolCallLatencySLABreach
  expr: |
    histogram_quantile(0.95,
      rate(contextiq_tool_call_duration_seconds_bucket[5m])
    ) > 3.0
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "p95 tool call latency exceeds 3 s SLA"
    description: "p95={{ $value | humanizeDuration }} over last 5 min"
```

**Grafana panel:** "Tool Call p50/p95/p99 Latency" using `histogram_quantile` over `contextiq_tool_call_duration_seconds_bucket`.

**Key span attributes:**

| Attribute | Value |
|---|---|
| `mcp.tool.name` | Tool name (e.g., `get_context`) |
| `mcp.request_id` | UUID of this specific call |
| `contextiq.user_id` | Authenticated user |
| `mcp.tool.success` | `true` / `false` |
| `mcp.tool.duration_ms` | Gateway-measured elapsed time |

## Acceptance Criteria

- [ ] Every `tools/call` produces a `mcp.tools.call` root span in Jaeger with `mcp.tool.name` and `mcp.request_id` attributes
- [ ] Agent Worker spans appear as child spans of `mcp.tools.call` in the same Jaeger trace — verified by `trace_id` match
- [ ] `contextiq_tool_call_duration_seconds` histogram is scraped by Prometheus and queryable
- [ ] `histogram_quantile(0.95, ...)` panel renders in Grafana for a sustained load test
- [ ] `ToolCallLatencySLABreach` alert fires in a test when calls are artificially delayed > 3 s
- [ ] Unit tests assert: span name, `mcp.tool.name`, `mcp.request_id`, and `traceparent` header presence on outbound Agent Worker request

## Dependencies

- TASK-US001-05 (OTel tracer provider configured, OTLP exporter running)
- TASK-US003-01 (root span wraps handler — start timing here)
- TASK-US003-02 (`traceparent` header injected in `AgentWorkerClient`)
- US-036 (Prometheus scraping and Grafana provisioning)

## Definition of Done

- [ ] `opentelemetry-propagate` `inject()` call confirmed in `AgentWorkerClient` via `pytest-httpx` header capture
- [ ] Jaeger trace in staging shows gateway → agent-worker → retrieval spans stitched in a single trace tree
- [ ] `PrometheusRule` for `ToolCallLatencySLABreach` merged into Helm chart and active in staging
- [ ] Load test (100 concurrent calls) shows p95 < 3 s and histogram populated correctly
- [ ] `mcp.tool.name` label cardinality acceptable — no unbounded label values in histogram
