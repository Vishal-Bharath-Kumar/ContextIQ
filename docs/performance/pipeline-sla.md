# Pipeline SLA — End-to-End Latency Budget

## Overview

The ContextIQ multi-agent pipeline is bound by a **p95 ≤ 3 s** SLA measured
from state initialisation in `POST /v1/execute` to receipt of `final_response`.

This document defines the per-node latency budget, the mathematical validation
model, and the operational alert configuration.

---

## Node Latency Budget

| Node | Median (ms) | p95 (ms) | Stub sleep | Present in paths |
|---|---|---|---|---|
| `intent_agent` | 200 | 400 | 200 ms | all |
| `retrieval_agent` | 800 | 1 200 | 800 ms | full, skip_compression |
| `governance_agent` | 100 | 200 | 100 ms | full, skip_compression |
| `compression_agent` | 200 | 400 | 200 ms | full only (~60 % of requests) |
| `routing_agent` | 50 | 100 | 50 ms | all |

### Path totals

| Path | Nodes | Median total | p95 total | SLA target |
|---|---|---|---|---|
| **full** (with compression) | all 5 | 1 350 ms | 2 300 ms | p95 < **3 000 ms** ✓ |
| **skip_compression** | 4 (no compression) | 1 150 ms | 1 900 ms | p95 < **2 000 ms** ✓ |
| **clarification** | intent only | 200 ms | 400 ms | no explicit SLA |
| **failed** | varies | — | — | no explicit SLA |

---

## SLA Validation Strategy

### 1. Benchmark tests (CI)

Latency benchmarks live in `tests/agents/test_pipeline_sla.py` and run in a
dedicated CI job:

```bash
pytest -m benchmark tests/agents/test_pipeline_sla.py --benchmark-json=benchmark-results.json
```

Each test uses **100 rounds + 10 warmup rounds** of calibrated stub nodes
(see `tests/agents/stubs/latency_nodes.py`) that replace real sub-agents with
`asyncio.sleep()` calls matching the median latency above.

| Test | Assertion |
|---|---|
| `test_pipeline_p95_under_3s` | `p95 < 3.0 s` (full path) |
| `test_pipeline_skip_compression_p95_under_2s` | `p95 < 2.0 s` (skip path) |
| `test_latency_model_sums_under_sla` | Arithmetic check on median sums |

### 2. Mathematical validation

For the full path:

$$p95_{total} = \sum_{n \in \text{nodes}} p95_n$$

$$= 400 + 1200 + 200 + 400 + 100 = 2300 \text{ ms} < 3000 \text{ ms} \checkmark$$

> **Note:** This is a conservative upper bound assuming all nodes simultaneously
> hit their individual p95. In practice, p95 is lower due to independence.

---

## Prometheus Histogram

The `contextiq_pipeline_e2e_duration_seconds` histogram is registered in
`src/agents/telemetry.py` and recorded in `POST /v1/execute` after
`graph.ainvoke()` returns.

```
contextiq_pipeline_e2e_duration_seconds{path="full"} — histogram
contextiq_pipeline_e2e_duration_seconds{path="skip_compression"} — histogram
contextiq_pipeline_e2e_duration_seconds{path="clarification"} — histogram
contextiq_pipeline_e2e_duration_seconds{path="failed"} — histogram
```

**Buckets:** `[0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0]` seconds

### Useful PromQL queries

```promql
# Current p95 across all paths
histogram_quantile(0.95,
  rate(contextiq_pipeline_e2e_duration_seconds_bucket[5m])
)

# p95 by path
histogram_quantile(0.95,
  rate(contextiq_pipeline_e2e_duration_seconds_bucket[5m])
) by (path)

# Request rate by path
sum(rate(contextiq_pipeline_e2e_duration_seconds_count[5m])) by (path)
```

---

## Prometheus Alert Rules

Alert rules are provisioned via the `PrometheusRule` custom resource in
`helm/charts/agent-worker/templates/prometheusrule.yaml`.

| Alert | Expression | Threshold | Severity | For |
|---|---|---|---|---|
| `PipelineSLABreach` | `histogram_quantile(0.95, rate(..._bucket[5m])) > 3.0` | > 3.0 s | critical | 3 min |
| `PipelineLatencyP99Elevated` | `histogram_quantile(0.99, rate(..._bucket[5m])) > 4.0` | > 4.0 s | warning | 5 min |

Enable / disable via Helm:

```yaml
# values.yaml
prometheusRule:
  enabled: true
  release: prometheus   # must match Prometheus Operator 'release' label selector
```

---

## Grafana Dashboard Panels

The **ContextIQ Agent Worker** Grafana dashboard should include:

### Pipeline E2E Latency (p50 / p95 / p99)

```promql
histogram_quantile(0.50, rate(contextiq_pipeline_e2e_duration_seconds_bucket[5m]))
histogram_quantile(0.95, rate(contextiq_pipeline_e2e_duration_seconds_bucket[5m]))
histogram_quantile(0.99, rate(contextiq_pipeline_e2e_duration_seconds_bucket[5m]))
```

- Time-series panel with `path` variable dropdown filter
- Threshold lines at 2 s (skip SLA), 3 s (full SLA)

### Node Duration Breakdown (p95)

```promql
histogram_quantile(0.95,
  rate(contextiq_pipeline_node_duration_seconds_bucket{status="success"}[5m])
) by (node_name)
```

- Bar gauge panel grouped by `node_name`
- Useful for identifying which node is causing SLA breaches

---

## References

- `tests/agents/test_pipeline_sla.py` — benchmark and unit tests
- `tests/agents/stubs/latency_nodes.py` — calibrated stub nodes
- `src/agents/telemetry.py` — Prometheus histogram definitions
- `helm/charts/agent-worker/templates/prometheusrule.yaml` — alert rules
- TASK-US006-01: Pipeline topology with conditional edges
- TASK-US006-03: Per-node `contextiq_pipeline_node_duration_seconds` histogram
