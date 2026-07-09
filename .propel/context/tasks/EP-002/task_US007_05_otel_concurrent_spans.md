# TASK-US007-05 — OTel Concurrent Span Instrumentation for Parallel Connector Calls

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US007-05 |
| User Story | US-007 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Observability |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Instrument each parallel connector `fetch()` call with its own child OTel span so that Jaeger renders all connector calls as concurrent sibling spans under the `pipeline.retrieval_agent` parent. This makes the parallelism visually verifiable and provides per-connector latency breakdown in production.

## Implementation Details

**Technology:** Python 3.11+, `opentelemetry-sdk`, `opentelemetry.context`

**File locations:**
- `src/agents/retrieval/parallel_dispatcher.py` — span creation in `_fetch_one` (extends TASK-US007-01 and TASK-US007-02)
- `tests/agents/test_retrieval_spans.py`

**The challenge — span context in concurrent tasks:**
`asyncio.gather` runs coroutines in the same event-loop thread but as independent tasks. OTel's context propagation uses Python's `contextvars` module, which isolates context per `asyncio.Task`. When `gather` creates tasks, each inherits a **copy** of the current context at creation time — the parent span is captured correctly.

**Span-per-connector inside `_fetch_one`:**
```python
async def _fetch_one(
    self,
    connector: BaseConnector,
    query: str,
    token_budget: int | None,
) -> FetchResult:
    tracer = trace.get_tracer("contextiq.retrieval")

    with tracer.start_as_current_span(
        f"connector.fetch.{connector.connector_type}",
        kind=trace.SpanKind.CLIENT,
    ) as span:
        span.set_attribute("connector.source_id",   connector.source_id)
        span.set_attribute("connector.type",        connector.connector_type)
        span.set_attribute("connector.token_budget", token_budget or 0)

        t_start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                connector.fetch(query=query, filters={"token_budget": token_budget}),
                timeout=self._get_timeout(connector.source_id),
            )
            elapsed_ms = int((time.monotonic() - t_start) * 1000)
            span.set_attribute("connector.chunks_returned", len(result.chunks))
            span.set_attribute("connector.duration_ms",     elapsed_ms)
            span.set_status(StatusCode.OK)
            # ... Prometheus metrics (TASK-US007-02)
            return result

        except asyncio.TimeoutError:
            span.set_status(StatusCode.ERROR, "timeout")
            span.set_attribute("connector.timed_out", True)
            # ... metrics and raise ConnectorTimeoutError

        except Exception as e:
            span.record_exception(e)
            span.set_status(StatusCode.ERROR, str(e))
            raise
```

**Expected Jaeger trace for a 4-connector parallel request:**
```
mcp.tools.call                                       0 ms ──────────────── 1 500 ms
  pipeline.intent_agent                              0 ms ─── 200 ms
  pipeline.retrieval_agent                         200 ms ──────────────── 1 200 ms
    connector.fetch.github      (concurrent)       200 ms ────────── 900 ms
    connector.fetch.confluence  (concurrent)       200 ms ──── 600 ms
    connector.fetch.jira        (concurrent)       200 ms ── 450 ms
    connector.fetch.grafana     (concurrent)       200 ms ─ 350 ms
  pipeline.governance_agent                      1 200 ms ─ 1 350 ms
```
The four `connector.fetch.*` spans overlap in the timeline — this is the visual proof of parallelism.

**Context propagation verification test:**
```python
async def test_connector_spans_are_children_of_retrieval_agent_span():
    exporter = InMemorySpanExporter()
    # ... configure tracer with exporter

    await dispatcher.fetch_all(query="...", source_ids=["github", "confluence"])

    spans = exporter.get_finished_spans()
    retrieval_span = next(s for s in spans if s.name == "pipeline.retrieval_agent")
    connector_spans = [s for s in spans if s.name.startswith("connector.fetch.")]

    for cs in connector_spans:
        assert cs.parent.span_id == retrieval_span.context.span_id
```

**Key span attributes:**

| Attribute | Value |
|---|---|
| `connector.source_id` | e.g. `github:myorg/myrepo` |
| `connector.type` | e.g. `github` |
| `connector.token_budget` | integer from execution plan |
| `connector.chunks_returned` | count on success |
| `connector.duration_ms` | wall-clock fetch time |
| `connector.timed_out` | `true` on timeout |

## Acceptance Criteria

- [ ] Each connector `fetch()` produces a `connector.fetch.<type>` span in Jaeger
- [ ] All connector spans share the same parent span ID (`pipeline.retrieval_agent`)
- [ ] Connector spans for a 4-connector request visually overlap in the Jaeger trace timeline (parallelism confirmed)
- [ ] Timed-out connectors produce a span with `status=ERROR` and `connector.timed_out=true`
- [ ] `connector.chunks_returned` attribute is present on all successful connector spans
- [ ] Unit test: `InMemorySpanExporter` confirms parent-child span relationship for all connector spans

## Dependencies

- TASK-US001-05 (OTel tracer provider configured; OTLP exporter to Jaeger)
- TASK-US007-01 (`_fetch_one` augmented with span)
- TASK-US007-02 (timeout error branch sets span status = ERROR)

## Definition of Done

- [ ] Span instrumentation merged into `_fetch_one` (single location — no duplication)
- [ ] Unit test asserts span parent-child relationship using `InMemorySpanExporter`
- [ ] Jaeger trace in staging shows concurrent connector spans for a real 3-connector request
- [ ] Grafana "Connector Latency by Source" panel added using `contextiq_connector_fetch_duration_seconds`
