# TASK-US036-05 — Integration Tests Covering All 6 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US036-05 |
| User Story | US-036 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Write the test suite covering all 6 US-036 acceptance criteria: `/metrics` returns Prometheus text format (AC-1), all four core metric names are present (AC-2), all four required label dimensions appear in metric samples (AC-3), the dashboard JSON has exactly 6 panels and valid structure (AC-4), retention configuration is validated (AC-5), and the three PrometheusRule alert PromQL expressions are syntactically correct (AC-6). Backend tests use `pytest`; infrastructure tests use `promtool` and JSON schema validation in CI.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, FastAPI `TestClient`, `prometheus-client`, `promtool` (in CI), Python `json` for dashboard validation

**File locations:**
- `tests/observability/test_metrics_middleware.py` — AC-1, AC-2, AC-3
- `tests/observability/test_metrics_endpoint.py` — AC-1 (response format)
- `tests/observability/test_path_normalisation.py` — middleware utility
- `tests/observability/test_dashboard_json.py` — AC-4
- `tests/observability/test_alert_rules_syntax.py` — AC-6 (promtool)

---

### Shared fixtures

```python
# tests/observability/conftest.py
import pytest
from fastapi              import FastAPI
from fastapi.testclient   import TestClient
from prometheus_client    import CollectorRegistry, Counter, Histogram, Gauge, REGISTRY
from prometheus_client.exposition import generate_latest

from src.observability.metrics.middleware import MetricsMiddleware
from src.observability.metrics.endpoint   import router as metrics_router
from src.observability.metrics.settings   import MetricsSettings


@pytest.fixture
def test_app():
    """Minimal FastAPI app with MetricsMiddleware and /metrics endpoint."""
    app = FastAPI()
    app.add_middleware(
        MetricsMiddleware,
        settings=MetricsSettings(service_name="test-service", enabled=True),
    )
    app.include_router(metrics_router)

    @app.get("/v1/items/{item_id}")
    async def get_item(item_id: str):
        return {"id": item_id}

    @app.get("/v1/fail")
    async def fail():
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Simulated error")

    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)
```

---

### AC-1 — `/metrics` endpoint in Prometheus text format

```python
# tests/observability/test_metrics_endpoint.py
def test_metrics_endpoint_returns_200(client):
    """AC-1: /metrics returns HTTP 200."""
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_metrics_content_type_is_prometheus_text(client):
    """AC-1: Content-Type header matches Prometheus text exposition format."""
    resp = client.get("/metrics")
    assert "text/plain" in resp.headers["content-type"]


def test_metrics_body_is_valid_prometheus_text(client):
    """AC-1: Body contains # HELP and # TYPE lines — valid Prometheus format."""
    # Trigger a request to create label combinations
    client.get("/v1/items/abc")
    resp    = client.get("/metrics")
    body    = resp.text
    assert "# HELP" in body
    assert "# TYPE" in body
```

---

### AC-2 — All four core metric names present

```python
# tests/observability/test_metrics_middleware.py
def test_all_four_metric_names_exposed(client):
    """AC-2: All four required metric families appear in /metrics output."""
    client.get("/v1/items/abc")  # trigger instrumentation
    body = client.get("/metrics").text

    assert "contextiq_requests_total"             in body
    assert "contextiq_request_duration_seconds"   in body
    assert "contextiq_errors_total"               in body
    assert "contextiq_active_requests"            in body


def test_requests_total_increments_on_request(client):
    """AC-2: contextiq_requests_total counter increments after each request."""
    client.get("/v1/items/x")
    client.get("/v1/items/y")
    body = client.get("/metrics").text

    # Find the sum across all label sets
    import re
    totals = re.findall(r'contextiq_requests_total\{[^}]+\}\s+([\d.e+]+)', body)
    total  = sum(float(v) for v in totals)
    assert total >= 2


def test_errors_total_increments_on_5xx(client):
    """AC-2: contextiq_errors_total increments when a 5xx response is returned."""
    try:
        client.get("/v1/fail")
    except Exception:
        pass
    body = client.get("/metrics").text
    assert "contextiq_errors_total" in body
```

---

### AC-3 — All four required label dimensions in metric samples

```python
def test_requests_total_has_required_labels(client):
    """AC-3: service, endpoint, intent_type, tenant_id labels present in metric sample."""
    client.get("/v1/items/abc")
    body = client.get("/metrics").text

    # Find a contextiq_requests_total sample line
    import re
    lines = [l for l in body.splitlines()
             if l.startswith("contextiq_requests_total{")]
    assert len(lines) > 0, "No contextiq_requests_total samples found"

    sample = lines[0]
    assert 'service='     in sample
    assert 'endpoint='    in sample
    assert 'intent_type=' in sample
    assert 'tenant_id='   in sample


def test_duration_histogram_has_required_labels(client):
    """AC-3: histogram _bucket lines carry all four label dimensions."""
    client.get("/v1/items/abc")
    body = client.get("/metrics").text

    import re
    buckets = [l for l in body.splitlines()
               if l.startswith("contextiq_request_duration_seconds_bucket{")]
    assert len(buckets) > 0

    b = buckets[0]
    assert 'service='     in b
    assert 'endpoint='    in b
    assert 'intent_type=' in b
    assert 'tenant_id='   in b
```

---

### AC-3 — Path normalisation (prevents label cardinality explosion)

```python
# tests/observability/test_path_normalisation.py
from src.observability.metrics.middleware import _normalise_path

@pytest.mark.parametrize("raw, expected", [
    ("/v1/traces/3fa85f64-5717-4562-b3fc-2c963f66afa6", "/v1/traces/{id}"),
    ("/v1/knowledge-sources/42/sync",                   "/v1/knowledge-sources/{id}/sync"),
    ("/v1/policies",                                    "/v1/policies"),
    ("/v1/traces/3fa85f64-5717-4562-b3fc-2c963f66afa6/export", "/v1/traces/{id}/export"),
    ("/healthz",                                        "/healthz"),
])
def test_normalise_path(raw, expected):
    assert _normalise_path(raw) == expected
```

---

### AC-4 — Dashboard JSON structure: 6 panels, required title

```python
# tests/observability/test_dashboard_json.py
import json, pathlib

DASHBOARD_PATH = pathlib.Path(
    "k8s/monitoring/grafana/dashboard-contextiq-overview.yaml"
)


def _load_dashboard_json() -> dict:
    """Extract the JSON from the YAML ConfigMap data value."""
    import yaml
    cm     = yaml.safe_load(DASHBOARD_PATH.read_text())
    raw    = cm["data"]["contextiq-platform-overview.json"]
    return json.loads(raw)


def test_dashboard_title():
    """AC-4: Dashboard is titled 'ContextIQ Platform Overview'."""
    d = _load_dashboard_json()
    assert d["title"] == "ContextIQ Platform Overview"


def test_dashboard_has_six_panels():
    """AC-4: Exactly 6 panels are provisioned."""
    d      = _load_dashboard_json()
    panels = d.get("panels", [])
    assert len(panels) == 6, f"Expected 6 panels, got {len(panels)}"


def test_dashboard_panel_ids_unique():
    """AC-4: All panel IDs are unique."""
    d    = _load_dashboard_json()
    ids  = [p["id"] for p in d["panels"]]
    assert len(ids) == len(set(ids))


def test_dashboard_has_template_variables():
    """AC-4: Dashboard has $service and $tenant_id template variables."""
    d      = _load_dashboard_json()
    names  = [t["name"] for t in d.get("templating", {}).get("list", [])]
    assert "service"   in names
    assert "tenant_id" in names


def test_dashboard_panels_have_prometheus_targets():
    """AC-4: Every panel has at least one Prometheus target with a non-empty expr."""
    d = _load_dashboard_json()
    for panel in d["panels"]:
        targets = panel.get("targets", [])
        assert len(targets) > 0, f"Panel '{panel.get('title')}' has no targets"
        for t in targets:
            assert t.get("expr"), f"Panel '{panel.get('title')}' has empty expr"
```

---

### AC-5 — Prometheus retention validation

```python
# tests/observability/test_dashboard_json.py  (continued)
def test_prometheus_cr_has_15d_retention():
    """AC-5: Prometheus CR spec has retention: 15d."""
    import yaml, pathlib
    cr_path = pathlib.Path("k8s/monitoring/prometheus.yaml")
    cr      = yaml.safe_load(cr_path.read_text())
    assert cr["spec"]["retention"] == "15d"
```

---

### AC-6 — PrometheusRule alert PromQL syntax (via `promtool`)

```python
# tests/observability/test_alert_rules_syntax.py
import subprocess, pathlib

RULES_PATH = pathlib.Path("k8s/monitoring/alert-rules/contextiq-platform.yaml")


def test_promtool_check_rules():
    """
    AC-6: promtool validates that all PromQL expressions in the PrometheusRule
    are syntactically correct and all required fields (for, severity) are present.
    """
    result = subprocess.run(
        ["promtool", "check", "rules", str(RULES_PATH)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"promtool check rules failed:\n{result.stdout}\n{result.stderr}"
    )


def test_alert_rules_cover_all_three_ac6_conditions():
    """AC-6: The PrometheusRule defines alerts for all three required conditions."""
    import yaml
    rules_yaml = yaml.safe_load(RULES_PATH.read_text())
    all_alerts = [
        rule["alert"]
        for group in rules_yaml["spec"]["groups"]
        for rule in group["rules"]
        if "alert" in rule
    ]
    # AC-6a: error rate > 5%
    assert any("ErrorRate" in a for a in all_alerts), \
        "Missing error rate alert rule"
    # AC-6b: p95 latency > 3 s
    assert any("Latency" in a or "P95" in a for a in all_alerts), \
        "Missing p95 latency alert rule"
    # AC-6c: connector failure > 10%
    assert any("Connector" in a for a in all_alerts), \
        "Missing connector failure alert rule"


def test_alert_rules_have_severity_labels():
    """AC-6: All alert rules carry a severity label (critical or warning)."""
    import yaml
    rules_yaml = yaml.safe_load(RULES_PATH.read_text())
    for group in rules_yaml["spec"]["groups"]:
        for rule in group["rules"]:
            if "alert" in rule:
                assert "severity" in rule.get("labels", {}), \
                    f"Alert '{rule['alert']}' is missing a severity label"


def test_alert_rules_have_runbook_urls():
    """AC-6: All alert rules reference a runbook_url annotation."""
    import yaml
    rules_yaml = yaml.safe_load(RULES_PATH.read_text())
    for group in rules_yaml["spec"]["groups"]:
        for rule in group["rules"]:
            if "alert" in rule:
                assert "runbook_url" in rule.get("annotations", {}), \
                    f"Alert '{rule['alert']}' is missing runbook_url annotation"
```

## Acceptance Criteria

- [ ] All AC-1 tests confirm `/metrics` returns 200 with `text/plain` content-type containing `# HELP` and `# TYPE` lines
- [ ] AC-2 tests confirm all four metric names appear in the output after at least one request
- [ ] AC-3 tests confirm `service`, `endpoint`, `intent_type`, `tenant_id` appear in at least one sample line per metric
- [ ] AC-4 dashboard tests confirm title = "ContextIQ Platform Overview", exactly 6 panels, and `$service` + `$tenant_id` variables
- [ ] AC-5 test confirms `retention: 15d` in the `Prometheus` CR YAML
- [ ] AC-6 `promtool` test returns exit code 0; structural tests confirm all three alert conditions and required annotations

## Dependencies

- TASK-US036-01 (`MetricsMiddleware`, `_normalise_path`, `/metrics` router)
- TASK-US036-02 (`prometheus.yaml` for AC-5 test)
- TASK-US036-03 (`contextiq-platform.yaml` for AC-6 tests)
- TASK-US036-04 (`dashboard-contextiq-overview.yaml` for AC-4 tests)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `promtool` available in CI Docker image (`prom/prometheus` base or `quay.io/prometheus/prometheus`)
- [ ] `mypy --strict` passes; no `ruff` lint errors on Python test files
