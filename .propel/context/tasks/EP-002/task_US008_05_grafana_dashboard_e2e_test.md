# TASK-US008-05 — Grafana Circuit-Breaker Dashboard and End-to-End Degradation Test

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US008-05 |
| User Story | US-008 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Observability / QA |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Provision a Grafana "Connector Health & Circuit Breakers" dashboard panel using the metrics from TASK-US008-04, add a Prometheus alert for sustained open-circuit connectors, and verify the end-to-end graceful-degradation path with an integration test: one connector down → pipeline completes → HTTP 200 with partial context and `degraded_sources`.

## Implementation Details

**Technology:** Grafana (dashboard JSON provisioned via ConfigMap), Prometheus `PrometheusRule`, `pytest`, `pytest-asyncio`

**File locations:**
- `helm/contextiq-agent-worker/templates/prometheusrule.yaml` — new alert rules (extends TASK-US006-05)
- `helm/contextiq-agent-worker/files/grafana-dashboard-connectors.json` — Grafana dashboard
- `tests/integration/test_graceful_degradation.py` — end-to-end degradation test

**Grafana "Connector Health & Circuit Breakers" dashboard panels:**

| Panel | Query | Description |
|---|---|---|
| Circuit Breaker State (table) | `contextiq_connector_circuit_breaker_state` | Per-connector state badge (green=closed, red=open, yellow=half-open) |
| Failure Rate by Connector | `rate(contextiq_connector_failure_count[5m])` | Stacked bar by `failure_type` label |
| Connector Fetch Duration (heatmap) | `contextiq_connector_fetch_duration_seconds_bucket` | p50/p95/p99 per connector |
| Circuit Open Duration | derived from state change events | Time-in-open per connector (Loki query on `connector_circuit_state_change` logs) |

**Prometheus alert rules:**
```yaml
groups:
  - name: connector_circuit_breakers
    rules:
      - alert: ConnectorCircuitBreakerOpen
        expr: contextiq_connector_circuit_breaker_state == 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Connector circuit breaker open: {{ $labels.connector_id }}"
          description: "Circuit has been open for > 2 min. Check connector health."

      - alert: ConnectorHighFailureRate
        expr: |
          rate(contextiq_connector_failure_count[5m]) > 0.5
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "High connector failure rate: {{ $labels.connector_id }}"
          description: "Failure rate {{ $value | humanize }}/s over last 5 min"

      - alert: AllConnectorsDown
        expr: |
          count(contextiq_connector_circuit_breaker_state == 1)
          == count(contextiq_connector_circuit_breaker_state >= 0)
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "ALL connectors have open circuit breakers"
          description: "Platform running with zero knowledge sources available"
```

**End-to-end degradation integration test:**
```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_partial_context_returned_when_one_connector_fails(
    agent_worker_client: AsyncClient,
    connector_registry: ConnectorRegistry,
):
    # Arrange: make GitHub connector raise ConnectionError on fetch()
    github_connector = connector_registry.get("github:test-org/test-repo")
    github_connector.fetch = AsyncMock(side_effect=ConnectionError("GitHub down"))

    # Act: invoke the pipeline
    response = await agent_worker_client.post("/v1/execute", json=make_execute_request(
        sources=["github:test-org/test-repo", "confluence:ENG"],
        prompt="How does the auth service work?",
    ))

    # Assert: HTTP 200 with partial context
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert len(body["output"]["context"]) > 0            # Confluence results present
    assert len(body["output"]["degraded_sources"]) == 1  # GitHub degraded
    assert body["output"]["degraded_sources"][0]["source_id"] == "github:test-org/test-repo"
    assert body["output"]["degraded_sources"][0]["error_type"] == "ConnectionError"

@pytest.mark.asyncio
@pytest.mark.integration
async def test_all_connectors_down_returns_200_with_empty_context(
    agent_worker_client, connector_registry
):
    # Make all connectors fail
    for source_id in connector_registry.active_source_ids():
        connector_registry.get(source_id).fetch = AsyncMock(side_effect=Exception("down"))

    response = await agent_worker_client.post("/v1/execute", json=make_execute_request(
        sources=connector_registry.active_source_ids(),
        prompt="Any prompt",
    ))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["output"]["context"] == []
    assert len(body["output"]["degraded_sources"]) == len(connector_registry.active_source_ids())

@pytest.mark.asyncio
@pytest.mark.integration
async def test_circuit_breaker_opens_after_5_failures(
    agent_worker_client, connector_registry, prometheus_registry
):
    github = connector_registry.get("github:test-org/test-repo")
    github.fetch = AsyncMock(side_effect=Exception("server error"))

    # Trigger 5 consecutive failures
    for _ in range(5):
        await agent_worker_client.post("/v1/execute", json=make_execute_request(
            sources=["github:test-org/test-repo"], prompt="test"
        ))

    # 6th request: circuit should be open — connector skipped
    response = await agent_worker_client.post("/v1/execute", json=make_execute_request(
        sources=["github:test-org/test-repo"], prompt="test"
    ))
    body = response.json()
    assert body["output"]["degraded_sources"][0]["error_type"] == "ConnectorCircuitOpenError"

    # Prometheus gauge should show state = 1 (open)
    state = prometheus_registry.get_sample_value(
        "contextiq_connector_circuit_breaker_state",
        {"connector_id": "github:test-org/test-repo"},
    )
    assert state == 1.0
```

## Acceptance Criteria

- [ ] Grafana "Connector Health & Circuit Breakers" dashboard renders with correct panels (provisioned via ConfigMap)
- [ ] `ConnectorCircuitBreakerOpen` alert fires within 2 min of a circuit opening in staging
- [ ] `AllConnectorsDown` critical alert fires when all connector circuits are open
- [ ] Integration test `test_partial_context_returned_when_one_connector_fails` passes
- [ ] Integration test `test_all_connectors_down_returns_200_with_empty_context` passes (never HTTP 500)
- [ ] Integration test `test_circuit_breaker_opens_after_5_failures` passes and confirms Prometheus gauge = 1

## Dependencies

- TASK-US008-04 (metrics available for dashboard queries)
- TASK-US008-03 (`degraded_sources` in response for test assertions)
- TASK-US008-01 (circuit-breaker thresholds for the 5-failure test)
- US-036 (Prometheus + Grafana provisioning infrastructure)

## Definition of Done

- [ ] Dashboard JSON committed to `helm/contextiq-agent-worker/files/` and auto-provisioned via Grafana sidecar
- [ ] Three `PrometheusRule` alerts merged into Helm chart and active in staging
- [ ] All 3 integration tests tagged `@pytest.mark.integration` pass in staging CI job
- [ ] Chaos test: kill Jira connector pod → `ConnectorCircuitBreakerOpen` alert fires → pipeline continues returning partial context
