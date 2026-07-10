# TASK-US009-05 — OTel Span Instrumentation and Latency Benchmark for Intent Classification

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US009-05 |
| User Story | US-009 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Observability |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Instrument `intent_node()` with an OpenTelemetry span that records the intent label, confidence score, and end-to-end classification latency. Add a CI benchmark test that asserts classification (with a mocked LLM) completes within 500 ms for a 2 000-token prompt.

## Implementation Details

**Technology:** Python 3.11+, `opentelemetry-api>=1.24`, `opentelemetry-sdk>=1.24`, `pytest-benchmark`

**File locations:**
- `src/agents/nodes/intent_node.py` — span instrumentation added to existing node
- `tests/agents/nodes/test_intent_node_benchmark.py` — latency benchmark test

**Span attributes (emitted on every `intent_node` execution):**

| Attribute key | Type | Example value |
|---|---|---|
| `intent.type` | string | `"debugging"` |
| `intent.confidence` | float | `0.87` |
| `intent.latency_ms` | float | `213.4` |
| `intent.low_confidence` | bool | `false` |

**Instrumented `intent_node()`:**

```python
# src/agents/nodes/intent_node.py  (extend TASK-US009-01 / TASK-US009-03)
import time
from opentelemetry import trace

_tracer = trace.get_tracer("contextiq.intent_agent")

async def intent_node(state: AgentState) -> dict:
    with _tracer.start_as_current_span("intent_agent.classify") as span:
        t0     = time.perf_counter()
        raw    = await _chain.ainvoke({"prompt_text": state["user_prompt"]})
        result = IntentResult.model_validate(raw)
        sources = select_sources(result.intent_type, result.confidence)
        latency_ms = (time.perf_counter() - t0) * 1000

        span.set_attributes({
            "intent.type":           result.intent_type,
            "intent.confidence":     result.confidence,
            "intent.latency_ms":     round(latency_ms, 2),
            "intent.low_confidence": result.confidence < INTENT_CONFIDENCE_THRESHOLD,
        })

        return {
            "intent_type":        result.intent_type,
            "intent_confidence":  result.confidence,
            "intent_source_list": sources,
        }
```

**CI benchmark test:**

```python
# tests/agents/nodes/test_intent_node_benchmark.py
import asyncio, pytest
from unittest.mock import AsyncMock, patch

PROMPT_2000_TOKENS = "def foo():\n    " + "pass\n    " * 400   # ≈ 2 000 tokens

@pytest.mark.benchmark(max_time=0.5)
def test_intent_node_latency(benchmark):
    mock_result = {"intent_type": "debugging", "confidence": 0.92, "reasoning": "test"}

    async def _run():
        with patch("src.agents.nodes.intent_node._chain") as mock_chain:
            mock_chain.ainvoke = AsyncMock(return_value=mock_result)
            from src.agents.nodes.intent_node import intent_node
            return await intent_node({"user_prompt": PROMPT_2000_TOKENS, "session_id": "bench"})

    result = benchmark(lambda: asyncio.run(_run()))
    assert result["intent_type"] == "debugging"
```

**OTel exporter configuration (no new env vars required):**
- The `_tracer` uses the globally configured OTLP exporter already set up in `src/gateway/telemetry.py` (EP-001, TASK-US001-05)
- In unit/benchmark tests the tracer uses the `NoOpTracer` by default — no real OTLP endpoint required

## Acceptance Criteria

- [ ] `intent.type`, `intent.confidence`, `intent.latency_ms`, and `intent.low_confidence` are set on the OTel span after every `intent_node` execution
- [ ] `intent.low_confidence = true` when `intent_confidence < 0.6`
- [ ] CI benchmark passes: mocked `intent_node` completes in < 500 ms for a 2 000-token prompt
- [ ] Span is a child of the parent pipeline span (context propagation via `_tracer.start_as_current_span`)
- [ ] OTel instrumentation does not alter the return value or error behaviour of `intent_node()`
- [ ] Unit tests assert all four span attribute values for both high- and low-confidence outcomes

## Dependencies

- TASK-US009-01 (`intent_node()` base implementation)
- TASK-US009-03 (`select_sources()` integrated into `intent_node()`)
- TASK-US009-04 (`INTENT_CONFIDENCE_THRESHOLD` constant)
- TASK-US001-05 (OTel tracer provider bootstrap — `src/gateway/telemetry.py`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Span attributes visible in Grafana Tempo trace viewer for a staging test run
- [ ] Benchmark test included in CI pipeline and fails the build if p95 latency > 500 ms
- [ ] `mypy --strict` passes; no `ruff` lint errors
