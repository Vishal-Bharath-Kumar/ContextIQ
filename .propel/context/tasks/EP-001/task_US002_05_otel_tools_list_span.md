# TASK-US002-05 — Instrument `tools/list` Calls with OpenTelemetry Spans

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US002-05 |
| User Story | US-002 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Observability |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Add OpenTelemetry instrumentation to the `tools/list` handler so that every call produces a traced span with cache hit/miss status, tool count, and latency attributes. Extends the OTel setup established in TASK-US001-05.

## Implementation Details

**Technology:** Python 3.11+, `opentelemetry-sdk`, `opentelemetry-instrumentation-redis` (for automatic Redis span), manual span for handler logic

**File locations:**
- `src/gateway/handlers/tools_list.py` — manual span wrapping the handler body
- `src/registry/cache/tool_cache.py` — span attributes for cache outcome
- `tests/gateway/test_tools_list_telemetry.py` — span attribute assertions

**Key implementation steps:**

1. Wrap the `tools/list` handler body in a manual span:
   ```python
   tracer = trace.get_tracer("contextiq.gateway")

   @mcp.list_tools()
   async def handle_tools_list() -> list[ToolDefinition]:
       with tracer.start_as_current_span("mcp.tools.list") as span:
           tools = await tool_registry_service.get_active_tools()
           span.set_attribute("mcp.tools.count", len(tools))
           return tools
   ```

2. Add cache outcome attribute inside `ToolListCache.get()`:
   ```python
   current_span = trace.get_current_span()
   if raw is None:
       current_span.set_attribute("contextiq.cache.hit", False)
       return None
   current_span.set_attribute("contextiq.cache.hit", True)
   ```

3. Enable `opentelemetry-instrumentation-redis` to automatically trace Redis `GET` and `SET` commands — install and call `RedisInstrumentor().instrument()` in `telemetry.py` alongside existing instrumentors.

4. Add Prometheus counter for `tools/list` call rate (separate from OTel):
   ```python
   tools_list_calls_total = Counter(
       "contextiq_tools_list_calls_total",
       "Total number of tools/list MCP calls",
       ["cache_hit"]
   )
   ```
   Increment with `cache_hit="true"` or `cache_hit="false"` label.

**Key span attributes to capture:**

| Attribute | Value |
|---|---|
| `mcp.tools.count` | Number of active tools returned |
| `contextiq.cache.hit` | `true` / `false` |
| `db.system` | `redis` (auto from Redis instrumentor) |
| `db.operation` | `GET` (auto from Redis instrumentor) |

## Acceptance Criteria

- [ ] Every `tools/list` call produces a `mcp.tools.list` span visible in Jaeger
- [ ] Span includes `mcp.tools.count` attribute matching the count of tools returned
- [ ] Span includes `contextiq.cache.hit` attribute correctly reflecting whether Redis cache was used
- [ ] Redis `GET` sub-span appears as a child of `mcp.tools.list` span
- [ ] Prometheus metric `contextiq_tools_list_calls_total{cache_hit="true"}` increments on cache hits
- [ ] Unit tests use `InMemorySpanExporter` to assert span name, attribute names, and attribute values

## Dependencies

- TASK-US001-05 (OTel tracer provider and OTLP exporter configured)
- TASK-US002-01 (`tools/list` handler)
- TASK-US002-03 (cache layer where `cache.hit` attribute is set)

## Definition of Done

- [ ] `opentelemetry-instrumentation-redis` added to `pyproject.toml`
- [ ] `RedisInstrumentor().instrument()` called in `telemetry.py` alongside `FastAPIInstrumentor`
- [ ] Unit tests assert: span name, `mcp.tools.count`, `contextiq.cache.hit` for both hit and miss cases
- [ ] Jaeger UI shows `mcp.tools.list` span with nested Redis `GET` child span in staging
- [ ] Grafana "Tools/List Cache Hit Rate" panel added using `contextiq_tools_list_calls_total` metric
