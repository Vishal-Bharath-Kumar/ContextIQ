# TASK-US036-02 — Kubernetes `ServiceMonitor` Resources and Prometheus Retention Configuration

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US036-02 |
| User Story | US-036 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the Kubernetes `ServiceMonitor` custom resources (one per ContextIQ service) that instruct the Prometheus Operator to scrape each service's `/metrics` endpoint on port `8080`. Configure the `Prometheus` CR with `retention: 15d` (AC-5). A single `ServiceMonitor` per service ensures Prometheus discovers new pod replicas automatically via label selectors without manual scrape-config updates.

## Implementation Details

**Technology:** Kubernetes YAML, Prometheus Operator CRDs (`monitoring.coreos.com/v1`)

**File locations:**
- `k8s/monitoring/service-monitors/contextiq-api.yaml`
- `k8s/monitoring/service-monitors/contextiq-gateway.yaml`
- `k8s/monitoring/service-monitors/contextiq-knowledge-agent.yaml`
- `k8s/monitoring/service-monitors/contextiq-governance.yaml`
- `k8s/monitoring/prometheus.yaml` — `Prometheus` CR spec (retention, scrape interval)

---

### Pattern: `ServiceMonitor` per service

All ContextIQ services follow an identical `ServiceMonitor` shape. Only `metadata.name` and `spec.selector.matchLabels.app` differ.

```yaml
# k8s/monitoring/service-monitors/contextiq-api.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: contextiq-api
  namespace: contextiq
  labels:
    # This label must match Prometheus CR's serviceMonitorSelector
    prometheus: contextiq
spec:
  selector:
    matchLabels:
      app: contextiq-api        # matches Service.metadata.labels.app
  namespaceSelector:
    matchNames:
      - contextiq
  endpoints:
    - port: http                # must match Service.spec.ports[].name
      path: /metrics
      interval: 15s
      scrapeTimeout: 10s
      honorLabels: false        # Prometheus labels take precedence (prevent label injection)
```

---

### All four service monitors (abbreviated)

```yaml
# k8s/monitoring/service-monitors/contextiq-gateway.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: contextiq-gateway
  namespace: contextiq
  labels:
    prometheus: contextiq
spec:
  selector:
    matchLabels:
      app: contextiq-gateway
  namespaceSelector:
    matchNames: [contextiq]
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
      scrapeTimeout: 10s
      honorLabels: false
---
# k8s/monitoring/service-monitors/contextiq-knowledge-agent.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: contextiq-knowledge-agent
  namespace: contextiq
  labels:
    prometheus: contextiq
spec:
  selector:
    matchLabels:
      app: contextiq-knowledge-agent
  namespaceSelector:
    matchNames: [contextiq]
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
      scrapeTimeout: 10s
      honorLabels: false
---
# k8s/monitoring/service-monitors/contextiq-governance.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: contextiq-governance
  namespace: contextiq
  labels:
    prometheus: contextiq
spec:
  selector:
    matchLabels:
      app: contextiq-governance
  namespaceSelector:
    matchNames: [contextiq]
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
      scrapeTimeout: 10s
      honorLabels: false
```

---

### `Prometheus` CR — retention and scrape configuration

```yaml
# k8s/monitoring/prometheus.yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: contextiq
  namespace: monitoring
spec:
  # AC-5: 15-day raw metric retention
  retention: 15d

  # Only pick up ServiceMonitors labelled prometheus=contextiq
  serviceMonitorSelector:
    matchLabels:
      prometheus: contextiq

  serviceMonitorNamespaceSelector:
    matchNames:
      - contextiq

  # Storage: 50 Gi PVC; resize as retention × ingestion_rate grows
  storage:
    volumeClaimTemplate:
      spec:
        accessModes: [ReadWriteOnce]
        resources:
          requests:
            storage: 50Gi

  # Resource limits — tune based on label cardinality
  resources:
    requests:
      cpu:    500m
      memory: 2Gi
    limits:
      cpu:    "2"
      memory: 4Gi

  # Global scrape defaults (overridden per ServiceMonitor endpoint)
  scrapeInterval: 15s
  evaluationInterval: 15s

  # Reference to the PrometheusRule namespace (TASK-US036-03)
  ruleSelector:
    matchLabels:
      prometheus: contextiq

  ruleNamespaceSelector:
    matchNames:
      - contextiq

  # Alertmanager integration (assumed pre-existing in the cluster)
  alerting:
    alertmanagers:
      - namespace: monitoring
        name: alertmanager-main
        port: web
```

---

### Matching `Service` port convention

Each ContextIQ Kubernetes `Service` must expose a port named `http` on `8080` for the `ServiceMonitor` endpoint `port: http` to resolve:

```yaml
# Example: k8s/services/contextiq-api-service.yaml (pattern — not a new file)
spec:
  ports:
    - name: http          # must match ServiceMonitor endpoint port
      port: 8080
      targetPort: 8080
      protocol: TCP
```

## Acceptance Criteria

- [ ] `kubectl apply -f k8s/monitoring/service-monitors/` creates all four `ServiceMonitor` resources without errors
- [ ] Prometheus Operator discovers and scrapes all four services (verified via Prometheus UI `Status → Targets`)
- [ ] `Prometheus` CR has `retention: 15d` — raw metrics older than 15 days are expired (AC-5)
- [ ] All `ServiceMonitor` resources carry `labels.prometheus: contextiq` matching the `Prometheus` CR's `serviceMonitorSelector`
- [ ] `honorLabels: false` is set on every endpoint — Prometheus-side labels cannot be overwritten by the application

## Dependencies

- TASK-US036-01 — services must expose `/metrics` on port `8080` for scraping to succeed
- EP-TECH-001 — Kubernetes namespace `contextiq` and Prometheus Operator must be pre-provisioned

## Definition of Done

- [ ] YAML lints with `kubectl apply --dry-run=client`
- [ ] Reviewed and merged to `main`
