# TASK-US006-03 — Node Entry/Exit Structured Logging with Per-Node Timing

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US006-03 |
| User Story | US-006 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Observability |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Add `with_node_logging` — a wrapper that emits a structured `structlog` entry at node entry and exit, records per-node duration, creates a child OTel span, and updates a Prometheus histogram. This provides both real-time pipeline visibility and the timing data needed to enforce the p95 < 3 s SLA (AC-6).

## Implementation Details

**Technology:** Python 3.11+, `structlog`, `opentelemetry-sdk`, `prometheus-client`

**File locations:**
- `src/agents/nodes/logging_wrapper.py` — `with_node_logging()` function
- `src/agents/telemetry.py` — OTel tracer and Prometheus histogram for node durations
- `tests/agents/test_node_logging.py`

**`with_node_logging` wrapper:**
```python
node_duration_histogram = Histogram(
    "contextiq_pipeline_node_duration_seconds",
    "Duration of each pipeline node execution",
    ["node_name", "status"],   # status: success | failed
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0],
)

def with_node_logging(node_fn: Callable, node_name: str) -> Callable:
    logger = structlog.get_logger("contextiq.pipeline.node").bind(node=node_name)
    tracer = trace.get_tracer("contextiq.agents")

    @functools.wraps(node_fn)
    async def wrapper(state: AgentState) -> dict:
        request_id = state["request_id"]
        bound = logger.bind(request_id=request_id, user_id=state["user_id"])

        with tracer.start_as_current_span(
            f"pipeline.{node_name}",
            kind=trace.SpanKind.INTERNAL,
        ) as span:
            span.set_attribute("pipeline.node_name", node_name)
            span.set_attribute("pipeline.request_id", request_id)

            bound.info("node_entry", node=node_name)
            t_start = time.monotonic()

            try:
                result = await node_fn(state)
                duration = time.monotonic() - t_start

                span.set_attribute("pipeline.duration_ms", int(duration * 1000))
                span.set_attribute("pipeline.status", "success")

                node_duration_histogram.labels(
                    node_name=node_name, status="success"
                ).observe(duration)

                bound.info(
                    "node_exit",
                    node=node_name,
                    duration_ms=round(duration * 1000, 1),
                    output_fields=list(result.keys()),
                )
                return result

            except Exception as e:
                duration = time.monotonic() - t_start
                span.record_exception(e)
                span.set_status(StatusCode.ERROR, str(e))
                node_duration_histogram.labels(
                    node_name=node_name, status="failed"
                ).observe(duration)
                bound.error(
                    "node_failed",
                    node=node_name,
                    duration_ms=round(duration * 1000, 1),
                    error=str(e),
                    exc_info=True,
                )
                raise

    return wrapper
```

**Log fields emitted per node:**

| Log event | Fields |
|---|---|
| `node_entry` | `node`, `request_id`, `user_id` |
| `node_exit` | `node`, `request_id`, `duration_ms`, `output_fields` (list of updated keys) |
| `node_failed` | `node`, `request_id`, `duration_ms`, `error` (string), `exc_info` |

**OTel span hierarchy for a complete request:**
```
mcp.tools.call                          [gateway — TASK-US003-05]
  └─ pipeline.intent_agent              [duration_ms = X]
  └─ pipeline.retrieval_agent           [duration_ms = Y]
  └─ pipeline.governance_agent          [duration_ms = Z]
  └─ pipeline.compression_agent         [duration_ms = W]
  └─ pipeline.routing_agent             [duration_ms = V]
```

**Grafana panel:** "Pipeline Node Duration Heatmap" — one row per node, coloured by p95 latency bucket.

## Acceptance Criteria

- [ ] `node_entry` log is emitted before the node function executes, containing `node` and `request_id`
- [ ] `node_exit` log is emitted after successful execution with `duration_ms` and `output_fields`
- [ ] `node_failed` log is emitted on exception with `error` message and stack trace
- [ ] OTel child span `pipeline.<node_name>` appears under `mcp.tools.call` root span in Jaeger
- [ ] Prometheus `contextiq_pipeline_node_duration_seconds` histogram is populated per node per status
- [ ] Log fields never include raw context content or PII (only field names, not values)
- [ ] Unit tests use `InMemorySpanExporter` and `caplog` to assert span and log attributes

## Dependencies

- TASK-US001-05 (OTel tracer provider configured — spans exported to Jaeger)
- TASK-US006-02 (`with_node_logging` composed inside `wrap()`)
- US-036 (Prometheus scraping)

## Definition of Done

- [ ] `structlog` configured with JSON renderer and ISO-8601 timestamp in production
- [ ] Unit test: `node_exit` log asserts `duration_ms` is numeric and > 0
- [ ] Integration test: 5-node pipeline execution visible as 5 child spans in a single Jaeger trace
- [ ] Grafana "Node Duration Heatmap" panel provisioned via ConfigMap
