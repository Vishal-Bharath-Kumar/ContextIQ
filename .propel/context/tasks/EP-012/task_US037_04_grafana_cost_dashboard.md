# TASK-US037-04 — Grafana "AI Cost & Efficiency" Dashboard ConfigMap

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US037-04 |
| User Story | US-037 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Provision the "AI Cost & Efficiency" Grafana dashboard as a Kubernetes `ConfigMap` auto-discovered by the `grafana-sc-dashboard` sidecar (same pattern as TASK-US036-04). The dashboard includes four required chart types from AC-3: daily cost by model, cost per user/team, compression savings %, and token budget utilisation. Four template variables satisfy AC-6 filters: `$date_range` (native Grafana time range), `$team`, `$model`, `$intent_type`.

## Implementation Details

**Technology:** Kubernetes YAML `ConfigMap`, Grafana JSON dashboard schema 36+

**File locations:**
- `k8s/monitoring/grafana/dashboard-ai-cost-efficiency.yaml`

---

### ConfigMap wrapper

```yaml
# k8s/monitoring/grafana/dashboard-ai-cost-efficiency.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-ai-cost-efficiency
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  ai-cost-efficiency.json: |
    <SEE DASHBOARD JSON BELOW>
```

---

### Dashboard JSON (`ai-cost-efficiency.json`)

```json
{
  "title": "AI Cost & Efficiency",
  "uid":   "ai-cost-efficiency-v1",
  "schemaVersion": 36,
  "refresh": "5m",
  "time": { "from": "now-24h", "to": "now" },
  "templating": {
    "list": [
      {
        "name":        "team",
        "label":       "Team",
        "type":        "query",
        "datasource":  "Prometheus",
        "query":       "label_values(contextiq_llm_cost_usd_total, team_id)",
        "multi":       true,
        "includeAll":  true,
        "current":     { "text": "All", "value": "$__all" }
      },
      {
        "name":        "model",
        "label":       "Model",
        "type":        "query",
        "datasource":  "Prometheus",
        "query":       "label_values(contextiq_llm_cost_usd_total, model_id)",
        "multi":       true,
        "includeAll":  true,
        "current":     { "text": "All", "value": "$__all" }
      },
      {
        "name":        "intent_type",
        "label":       "Intent",
        "type":        "query",
        "datasource":  "Prometheus",
        "query":       "label_values(contextiq_llm_cost_usd_total, intent_type)",
        "multi":       true,
        "includeAll":  true,
        "current":     { "text": "All", "value": "$__all" }
      },
      {
        "name":        "tenant_id",
        "label":       "Tenant",
        "type":        "query",
        "datasource":  "Prometheus",
        "query":       "label_values(contextiq_llm_cost_usd_total, tenant_id)",
        "multi":       false,
        "includeAll":  true,
        "current":     { "text": "All", "value": "$__all" }
      }
    ]
  },
  "panels": [

    {
      "id":    1,
      "title": "Daily LLM Cost by Model (USD)",
      "type":  "timeseries",
      "description": "AC-3: daily cost by model — cumulative USD spend per model per day.",
      "gridPos": { "x": 0, "y": 0, "w": 12, "h": 9 },
      "fieldConfig": {
        "defaults": {
          "unit": "currencyUSD",
          "custom": { "lineWidth": 2, "fillOpacity": 10 }
        }
      },
      "options": {
        "tooltip": { "mode": "multi" }
      },
      "targets": [
        {
          "expr": "sum by (model_id) (increase(contextiq_llm_cost_usd_total{team_id=~\"$team\", model_id=~\"$model\", intent_type=~\"$intent_type\", tenant_id=~\"$tenant_id\"}[$__range]))",
          "legendFormat": "{{ model_id }}",
          "datasource": "Prometheus"
        }
      ]
    },

    {
      "id":    2,
      "title": "Cost per Team (USD) — Last 24 h",
      "type":  "bargauge",
      "description": "AC-3: cost per user/team — horizontal bars per team, filtered by $team.",
      "gridPos": { "x": 12, "y": 0, "w": 12, "h": 9 },
      "fieldConfig": {
        "defaults": {
          "unit": "currencyUSD",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "value": null,  "color": "green"  },
              { "value": 10,    "color": "yellow" },
              { "value": 50,    "color": "red"    }
            ]
          }
        }
      },
      "options": {
        "orientation":   "horizontal",
        "reduceOptions": { "calcs": ["sum"] },
        "showUnfilled":  true
      },
      "targets": [
        {
          "expr": "sum by (team_id) (increase(contextiq_llm_cost_usd_total{model_id=~\"$model\", intent_type=~\"$intent_type\", tenant_id=~\"$tenant_id\"}[24h]))",
          "legendFormat": "{{ team_id }}",
          "datasource": "Prometheus",
          "instant": true
        }
      ]
    },

    {
      "id":    3,
      "title": "Compression Savings % (avg per request)",
      "type":  "gauge",
      "description": "AC-3: compression savings % — average ratio of tokens saved by the compression node.",
      "gridPos": { "x": 0, "y": 9, "w": 6, "h": 8 },
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min":  0,
          "max":  100,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "value": null, "color": "red"    },
              { "value": 20,   "color": "yellow" },
              { "value": 40,   "color": "green"  }
            ]
          }
        }
      },
      "options": {
        "reduceOptions": { "calcs": ["mean"] },
        "showThresholdLabels": false
      },
      "targets": [
        {
          "expr": "100 * histogram_quantile(0.50, sum by (le) (rate(contextiq_compression_savings_ratio_bucket{team_id=~\"$team\", intent_type=~\"$intent_type\", tenant_id=~\"$tenant_id\"}[$__range])))",
          "legendFormat": "Median compression savings %",
          "datasource": "Prometheus",
          "instant": true
        }
      ]
    },

    {
      "id":    4,
      "title": "Token Budget Utilisation",
      "type":  "timeseries",
      "description": "AC-3: token budget utilisation — prompt + completion tokens over time vs. a configurable budget threshold.",
      "gridPos": { "x": 6, "y": 9, "w": 18, "h": 8 },
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "custom": { "lineWidth": 2 }
        },
        "overrides": [
          {
            "matcher": { "id": "byName", "options": "Budget Threshold" },
            "properties": [
              { "id": "custom.lineStyle", "value": { "fill": "dash" } },
              { "id": "color",            "value": { "mode": "fixed", "fixedColor": "red" } }
            ]
          }
        ]
      },
      "targets": [
        {
          "expr": "sum by (model_id) (rate(contextiq_llm_tokens_total{token_type=\"prompt\", model_id=~\"$model\", team_id=~\"$team\", intent_type=~\"$intent_type\", tenant_id=~\"$tenant_id\"}[$__rate_interval]))",
          "legendFormat": "prompt — {{ model_id }}",
          "datasource": "Prometheus"
        },
        {
          "expr": "sum by (model_id) (rate(contextiq_llm_tokens_total{token_type=\"completion\", model_id=~\"$model\", team_id=~\"$team\", intent_type=~\"$intent_type\", tenant_id=~\"$tenant_id\"}[$__rate_interval]))",
          "legendFormat": "completion — {{ model_id }}",
          "datasource": "Prometheus"
        }
      ]
    },

    {
      "id":    5,
      "title": "Total Tokens Saved by Compression Engine",
      "type":  "stat",
      "description": "Cumulative tokens eliminated by compression — ROI indicator.",
      "gridPos": { "x": 0, "y": 17, "w": 6, "h": 6 },
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "color": { "mode": "thresholds" },
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "value": null,      "color": "blue" },
              { "value": 1000000,   "color": "green" }
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
          "expr": "sum(contextiq_compression_savings_tokens_total{team_id=~\"$team\", intent_type=~\"$intent_type\", tenant_id=~\"$tenant_id\"})",
          "legendFormat": "tokens saved",
          "datasource": "Prometheus",
          "instant": true
        }
      ]
    },

    {
      "id":    6,
      "title": "Compression Savings Ratio Distribution",
      "type":  "histogram",
      "description": "Distribution of per-request compression ratios — shows whether savings are consistent or bimodal.",
      "gridPos": { "x": 6, "y": 17, "w": 18, "h": 6 },
      "fieldConfig": {
        "defaults": { "unit": "percentunit" }
      },
      "targets": [
        {
          "expr": "sum by (le) (rate(contextiq_compression_savings_ratio_bucket{team_id=~\"$team\", intent_type=~\"$intent_type\", tenant_id=~\"$tenant_id\"}[$__rate_interval]))",
          "legendFormat": "{{le}}",
          "datasource": "Prometheus",
          "format": "heatmap"
        }
      ]
    }

  ]
}
```

## Acceptance Criteria

- [ ] `kubectl apply -f k8s/monitoring/grafana/dashboard-ai-cost-efficiency.yaml` creates the ConfigMap
- [ ] Grafana auto-discovers "AI Cost & Efficiency" dashboard within 60 s (AC-3)
- [ ] Dashboard contains all four AC-3 chart types: daily cost by model (panel 1), cost per user/team (panel 2), compression savings % (panel 3), token budget utilisation (panel 4)
- [ ] Four template variables exist: `$team`, `$model`, `$intent_type`, `$tenant_id` — matching AC-6 required filters (`date range` is the native Grafana time picker)
- [ ] Panel 2 "Cost per Team" bar gauge groups by `team_id` label
- [ ] Panel 3 "Compression Savings %" uses `contextiq_compression_savings_ratio_bucket` (from TASK-US037-02)
- [ ] Panel 4 "Token Budget Utilisation" shows prompt and completion tokens split by `model_id`

## Dependencies

- TASK-US036-04 (Grafana sidecar provisioning pattern — same ConfigMap label)
- TASK-US037-02 (`contextiq_compression_savings_ratio` histogram metric)
- TASK-US037-03 (`contextiq_llm_cost_usd_total`, `contextiq_llm_tokens_total` counters)

## Definition of Done

- [ ] Dashboard JSON validates via Grafana `/api/dashboards/import` (HTTP 200)
- [ ] YAML lints with `kubectl apply --dry-run=client`
- [ ] Reviewed and merged to `main`
