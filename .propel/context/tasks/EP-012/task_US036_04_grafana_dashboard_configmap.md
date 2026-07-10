# TASK-US036-04 — Grafana "ContextIQ Platform Overview" Dashboard ConfigMap (6 Panels)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US036-04 |
| User Story | US-036 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Provision the "ContextIQ Platform Overview" Grafana dashboard as a Kubernetes `ConfigMap` that the Grafana sidecar auto-discovers via the `grafana_dashboard: "1"` label (AC-4). The dashboard contains exactly 6 panels driven by the RED metrics defined in TASK-US036-01: Requests per Second, Latency p50/p95/p99, Error Rate %, Active Requests, Error Rate by Service, and Connector Failure Rate. All panels use `$service`, `$tenant_id`, and `$time_range` template variables for interactive filtering.

## Implementation Details

**Technology:** Kubernetes YAML `ConfigMap`, Grafana JSON dashboard schema 36+

**File locations:**
- `k8s/monitoring/grafana/dashboard-contextiq-overview.yaml` — ConfigMap containing the dashboard JSON

---

### ConfigMap wrapper

```yaml
# k8s/monitoring/grafana/dashboard-contextiq-overview.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-contextiq-overview
  namespace: monitoring
  labels:
    # Grafana sidecar (grafana-sc-dashboard) watches for this label
    grafana_dashboard: "1"
data:
  contextiq-platform-overview.json: |
    <SEE DASHBOARD JSON BELOW>
```

---

### Dashboard JSON (`contextiq-platform-overview.json`)

```json
{
  "title": "ContextIQ Platform Overview",
  "uid":   "contextiq-overview-v1",
  "schemaVersion": 36,
  "refresh": "30s",
  "time": { "from": "now-3h", "to": "now" },
  "templating": {
    "list": [
      {
        "name":       "service",
        "label":      "Service",
        "type":       "query",
        "datasource": "Prometheus",
        "query":      "label_values(contextiq_requests_total, service)",
        "multi":      true,
        "includeAll": true,
        "current":    { "text": "All", "value": "$__all" }
      },
      {
        "name":       "tenant_id",
        "label":      "Tenant",
        "type":       "query",
        "datasource": "Prometheus",
        "query":      "label_values(contextiq_requests_total, tenant_id)",
        "multi":      true,
        "includeAll": true,
        "current":    { "text": "All", "value": "$__all" }
      }
    ]
  },
  "panels": [

    {
      "id":    1,
      "title": "Requests per Second (RPS)",
      "type":  "timeseries",
      "gridPos": { "x": 0, "y": 0, "w": 12, "h": 8 },
      "fieldConfig": {
        "defaults": {
          "unit": "reqps",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "value": null,  "color": "green" },
              { "value": 100,   "color": "yellow" },
              { "value": 500,   "color": "red" }
            ]
          }
        }
      },
      "targets": [
        {
          "expr": "sum by (service) (rate(contextiq_requests_total{service=~\"$service\", tenant_id=~\"$tenant_id\"}[$__rate_interval]))",
          "legendFormat": "{{ service }}",
          "datasource": "Prometheus"
        }
      ]
    },

    {
      "id":    2,
      "title": "Request Latency — p50 / p95 / p99",
      "type":  "timeseries",
      "gridPos": { "x": 12, "y": 0, "w": 12, "h": 8 },
      "fieldConfig": {
        "defaults": {
          "unit": "s",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "value": null, "color": "green" },
              { "value": 1.5,  "color": "yellow" },
              { "value": 3.0,  "color": "red" }
            ]
          }
        }
      },
      "targets": [
        {
          "expr": "histogram_quantile(0.50, sum by (service, le) (rate(contextiq_request_duration_seconds_bucket{service=~\"$service\", tenant_id=~\"$tenant_id\"}[$__rate_interval])))",
          "legendFormat": "p50 {{ service }}",
          "datasource": "Prometheus"
        },
        {
          "expr": "histogram_quantile(0.95, sum by (service, le) (rate(contextiq_request_duration_seconds_bucket{service=~\"$service\", tenant_id=~\"$tenant_id\"}[$__rate_interval])))",
          "legendFormat": "p95 {{ service }}",
          "datasource": "Prometheus"
        },
        {
          "expr": "histogram_quantile(0.99, sum by (service, le) (rate(contextiq_request_duration_seconds_bucket{service=~\"$service\", tenant_id=~\"$tenant_id\"}[$__rate_interval])))",
          "legendFormat": "p99 {{ service }}",
          "datasource": "Prometheus"
        }
      ]
    },

    {
      "id":    3,
      "title": "Error Rate %",
      "type":  "timeseries",
      "gridPos": { "x": 0, "y": 8, "w": 8, "h": 8 },
      "fieldConfig": {
        "defaults": {
          "unit": "percentunit",
          "min":  0,
          "max":  1,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "value": null, "color": "green" },
              { "value": 0.02, "color": "yellow" },
              { "value": 0.05, "color": "red" }
            ]
          }
        }
      },
      "targets": [
        {
          "expr": "sum by (service) (rate(contextiq_errors_total{service=~\"$service\", tenant_id=~\"$tenant_id\"}[$__rate_interval])) / sum by (service) (rate(contextiq_requests_total{service=~\"$service\", tenant_id=~\"$tenant_id\"}[$__rate_interval]))",
          "legendFormat": "error rate — {{ service }}",
          "datasource": "Prometheus"
        }
      ]
    },

    {
      "id":    4,
      "title": "Active Requests",
      "type":  "stat",
      "gridPos": { "x": 8, "y": 8, "w": 4, "h": 8 },
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "value": null, "color": "green" },
              { "value": 50,   "color": "yellow" },
              { "value": 200,  "color": "red" }
            ]
          }
        }
      },
      "options": {
        "reduceOptions": { "calcs": ["lastNotNull"] },
        "colorMode": "background"
      },
      "targets": [
        {
          "expr": "sum by (service) (contextiq_active_requests{service=~\"$service\", tenant_id=~\"$tenant_id\"})",
          "legendFormat": "{{ service }}",
          "datasource": "Prometheus"
        }
      ]
    },

    {
      "id":    5,
      "title": "Error Rate by Service (Heatmap)",
      "type":  "bargauge",
      "gridPos": { "x": 12, "y": 8, "w": 12, "h": 8 },
      "fieldConfig": {
        "defaults": {
          "unit": "percentunit",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "value": null, "color": "green" },
              { "value": 0.02, "color": "yellow" },
              { "value": 0.05, "color": "red" }
            ]
          }
        }
      },
      "options": {
        "orientation":  "horizontal",
        "reduceOptions": { "calcs": ["mean"] },
        "showUnfilled": true
      },
      "targets": [
        {
          "expr": "sum by (service) (rate(contextiq_errors_total{tenant_id=~\"$tenant_id\"}[5m])) / sum by (service) (rate(contextiq_requests_total{tenant_id=~\"$tenant_id\"}[5m]))",
          "legendFormat": "{{ service }}",
          "datasource": "Prometheus",
          "instant": true
        }
      ]
    },

    {
      "id":    6,
      "title": "Connector Failure Rate %",
      "type":  "timeseries",
      "gridPos": { "x": 0, "y": 16, "w": 24, "h": 8 },
      "fieldConfig": {
        "defaults": {
          "unit": "percentunit",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "value": null, "color": "green" },
              { "value": 0.05, "color": "yellow" },
              { "value": 0.10, "color": "red" }
            ]
          }
        }
      },
      "targets": [
        {
          "expr": "sum by (service, tenant_id) (rate(contextiq_errors_total{endpoint=~\"/v1/knowledge-sources.*\", tenant_id=~\"$tenant_id\"}[$__rate_interval])) / sum by (service, tenant_id) (rate(contextiq_requests_total{endpoint=~\"/v1/knowledge-sources.*\", tenant_id=~\"$tenant_id\"}[$__rate_interval]))",
          "legendFormat": "connector failures — {{ service }} / {{ tenant_id }}",
          "datasource": "Prometheus"
        }
      ]
    }

  ]
}
```

---

### Grafana dashboard provisioning ConfigMap (sidecar pattern)

The Grafana deployment uses `grafana-sc-dashboard` sidecar (kube-prometheus-stack default). ConfigMaps labelled `grafana_dashboard: "1"` in the `monitoring` namespace are automatically loaded — no Grafana restart required.

```yaml
# In grafana Helm values (kube-prometheus-stack) — confirm this is already set:
grafana:
  sidecar:
    dashboards:
      enabled:   true
      label:     grafana_dashboard
      labelValue: "1"
      searchNamespace: monitoring
```

## Acceptance Criteria

- [ ] `kubectl apply -f k8s/monitoring/grafana/dashboard-contextiq-overview.yaml` creates the ConfigMap without errors
- [ ] Grafana auto-discovers and displays "ContextIQ Platform Overview" within 60 s (AC-4)
- [ ] Dashboard contains exactly 6 panels (AC-4): RPS, Latency p50/p95/p99, Error Rate %, Active Requests, Error Rate by Service, Connector Failure Rate
- [ ] `$service` and `$tenant_id` template variables populate from live Prometheus label values
- [ ] Error Rate % panel threshold turns red at 5% (aligned with AC-6 alert threshold)
- [ ] Latency panel threshold turns red at 3 s (aligned with AC-6 alert threshold)

## Dependencies

- TASK-US036-01 — metrics must exist with correct label names for PromQL queries to resolve
- TASK-US036-02 — Prometheus must be scraping services; Grafana Prometheus datasource named `"Prometheus"` must be pre-configured

## Definition of Done

- [ ] Dashboard JSON validates with `grafana-cli` or Grafana's `/api/dashboards/import` endpoint (HTTP 200)
- [ ] Reviewed and merged to `main`
