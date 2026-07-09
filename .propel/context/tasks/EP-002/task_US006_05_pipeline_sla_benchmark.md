# TASK-US006-05 — End-to-End Pipeline SLA Benchmark (p95 < 3 s)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US006-05 |
| User Story | US-006 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | QA / Performance |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Establish a pipeline-level p95 latency benchmark using latency-simulating node stubs that model realistic sub-agent durations. Validate the 3 s SLA mathematically and in CI, and provision a Prometheus alert that fires when the production pipeline breaches the threshold.

## Implementation Details

**Technology:** Python 3.11+, `pytest`, `pytest-asyncio`, `pytest-benchmark`, `locust` (load test), Prometheus `Histogram`

**File locations:**
- `tests/agents/test_pipeline_sla.py` — benchmark and latency model tests
- `tests/agents/stubs/latency_nodes.py` — calibrated stub nodes with `asyncio.sleep`
- `helm/contextiq-agent-worker/templates/prometheusrule.yaml` — SLA alert rule

**Realistic latency model per node (stub `asyncio.sleep` durations based on design estimates):**

| Node | Median | p95 | Stub sleep |
|---|---|---|---|
| `intent_agent` | 200 ms | 400 ms | 200 ms |
| `retrieval_agent` | 800 ms | 1 200 ms | 800 ms |
| `governance_agent` | 100 ms | 200 ms | 100 ms |
| `compression_agent` | 200 ms | 400 ms | 200 ms (skipped ~40% of requests) |
| `routing_agent` | 50 ms | 100 ms | 50 ms |
| **Total (with compression)** | **1 350 ms** | **2 300 ms** | **< 3 000 ms** ✓ |

**Calibrated stub nodes:**
```python
# stubs/latency_nodes.py
async def stub_intent_node(state: AgentState) -> dict:
    await asyncio.sleep(0.200)
    return {
        "intent_type": "debugging",
        "intent_confidence": 0.85,
        "execution_plan": {"token_budget_total": 8000, "sources": ["github", "confluence"]},
        "status": ExecutionStatus.RUNNING,
        "current_node": "intent_agent",
    }

async def stub_retrieval_node(state: AgentState) -> dict:
    await asyncio.sleep(0.800)
    chunks = [{"id": f"c{i}", "content": "x" * 100, "token_count": 80} for i in range(20)]
    return {"raw_context": chunks, "ranked_context": chunks, "current_node": "retrieval_agent"}

# ... (governance: 100 ms, compression: 200 ms, routing: 50 ms)
```

**Benchmark test:**
```python
@pytest.mark.asyncio
@pytest.mark.benchmark(group="e2e-pipeline")
async def test_pipeline_p95_under_3s(benchmark):
    """E2E pipeline (with compression path) must complete in < 3 s at p95"""
    stub_graph = build_stub_graph()   # graph built with latency stubs
    initial_state = make_initial_state(prompt="Why is service X slow?")
    config = {"configurable": {"thread_id": str(uuid4())}}

    result = await benchmark.pedantic(
        lambda: stub_graph.ainvoke(initial_state, config=config),
        rounds=100,
        warmup_rounds=10,
    )

    # Assert p95 from benchmark stats
    assert benchmark.stats["q95"] < 3.0     # 3 s
    assert result["status"] == ExecutionStatus.COMPLETE
```

**Compression-skip path benchmark (faster path):**
```python
async def test_pipeline_skip_compression_p95_under_2s(benchmark):
    """Without compression (tokens ≤ budget), p95 must be < 2 s"""
    stub_graph = build_stub_graph(compression_skip=True)
    # ... benchmark rounds=100, assert q95 < 2.0
```

**Prometheus SLA alert rule:**
```yaml
# helm/contextiq-agent-worker/templates/prometheusrule.yaml
- alert: PipelineSLABreach
  expr: |
    histogram_quantile(0.95,
      rate(contextiq_pipeline_e2e_duration_seconds_bucket[5m])
    ) > 3.0
  for: 3m
  labels:
    severity: critical
  annotations:
    summary: "Pipeline p95 latency exceeds 3 s SLA"
    description: "Current p95={{ $value | humanizeDuration }}"
```

**E2E pipeline duration histogram** (registered in `src/agents/telemetry.py`):
```python
pipeline_e2e_duration = Histogram(
    "contextiq_pipeline_e2e_duration_seconds",
    "Full pipeline execution time from state init to final_response",
    ["path"],     # path: full | skip_compression | clarification | failed
    buckets=[0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0],
)
```
Recorded in `POST /v1/execute` after `graph.ainvoke()` returns, labeled by `path` derived from `final_state["current_node"]` history.

## Acceptance Criteria

- [ ] Benchmark: `q95 < 3.0 s` asserted in CI for the full-pipeline stub (100 rounds)
- [ ] Benchmark: `q95 < 2.0 s` asserted in CI for the compression-skip stub path
- [ ] `contextiq_pipeline_e2e_duration_seconds` histogram is queryable in Prometheus with `path` label
- [ ] `PipelineSLABreach` alert fires within 3 min when stub nodes are slowed to > 3 s total (chaos test in staging)
- [ ] Grafana "Pipeline E2E Latency (p50/p95/p99)" panel renders correctly with `path` filter dropdown

## Dependencies

- TASK-US006-01 (full pipeline topology with conditional edges)
- TASK-US006-03 (`contextiq_pipeline_node_duration_seconds` per-node histogram)
- US-036 (Prometheus scraping and Grafana provisioning)

## Definition of Done

- [ ] Benchmark runs in CI `pytest -m benchmark` job; results stored as artifact
- [ ] `PipelineSLABreach` Prometheus alert merged into `helm/contextiq-agent-worker` chart
- [ ] Grafana dashboard updated with "Pipeline E2E Latency" and "Node Duration Breakdown" panels
- [ ] Budget allocation table (node × median × p95) documented in `docs/performance/pipeline-sla.md`
