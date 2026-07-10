# TASK-US046-02 — Prometheus Adapter: Bridge `contextiq_active_requests` to Kubernetes Custom Metrics API

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US046-02 |
| User Story | US-046 |
| Epic | EP-TECH-001 — Platform Infrastructure & Kubernetes |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Install the Prometheus Adapter (AC-2) and configure it to expose `contextiq_active_requests` (defined in US-036 TASK-US036-01 as a `prometheus_client.Gauge` scraped by Prometheus) as a Kubernetes custom metric at `custom.metrics.k8s.io/v1beta1`. The HPA for `contextiq-agent-worker` (TASK-US046-03) reads this metric to scale on active request depth. The adapter is deployed via Helm in the `contextiq-observability` namespace and references the in-cluster Prometheus service.

## Implementation Details

**Technology:** `prometheus-adapter` Helm chart (`prometheus-community/prometheus-adapter`), Kubernetes `custom.metrics.k8s.io/v1beta1` API

**File locations:**
- `helm/charts/prometheus-adapter/values.yaml` — adapter configuration (Prometheus URL + rules)
- `helm/charts/prometheus-adapter/values-prod.yaml`
- `argocd/apps/services/prometheus-adapter.yaml` — ArgoCD Application (adds to App-of-Apps)

---

### Prometheus Adapter Helm values

```yaml
# helm/charts/prometheus-adapter/values.yaml
# Prometheus Adapter bridges Prometheus metrics → Kubernetes custom.metrics.k8s.io API.
# The HPA controller polls this API to get the current value of custom metrics.

prometheus:
  # In-cluster Prometheus URL (deployed in contextiq-observability)
  url:  http://prometheus.contextiq-observability.svc.cluster.local
  port: 9090

# metricsRelistInterval: how often the adapter re-lists metric names from Prometheus
metricsRelistInterval: 30s

# logLevel: 0 = errors only, 6 = very verbose (use 4 in staging for debugging)
logLevel: 0

replicas: 2   # HA — two adapter replicas for reliability

resources:
  requests:
    cpu:    "100m"
    memory: "128Mi"
  limits:
    cpu:    "500m"
    memory: "256Mi"

# AC-2: Custom metric rules
# Each rule selects a Prometheus metric and exposes it on the custom metrics API.
#
# Rule anatomy:
#   seriesQuery:  PromQL selector to match series (must return a Gauge/Counter)
#   resources:    maps Prometheus labels to Kubernetes resource dimensions
#     overrides:  explicit label → {resource, group} mappings
#   name:         the custom metric name as it appears under custom.metrics.k8s.io
#   metricsQuery: PromQL expression evaluated when the HPA requests the metric value
#                 <<.LabelMatchers>> is replaced by the HPA's namespace/pod selectors
rules:
  custom:
    # contextiq_active_requests  — used by agent-worker HPA (AC-2)
    # The metric is a per-pod Gauge incremented/decremented by MetricsMiddleware (US-036).
    # We aggregate across pods in the target Deployment and average over replicas so the
    # HPA gets a per-replica load figure, enabling predictable scale-up.
    - seriesQuery: >
        contextiq_active_requests{namespace!="",pod!=""}
      resources:
        overrides:
          namespace: { resource: namespace }
          pod:       { resource: pod }
      name:
        matches:     "contextiq_active_requests"
        as:          "contextiq_active_requests"    # metric name on custom.metrics.k8s.io
      metricsQuery: >
        sum(contextiq_active_requests{<<.LabelMatchers>>}) by (pod)

    # contextiq_requests_total rate — available as a second custom metric
    # Not used by HPA directly but useful for load-based dashboards.
    - seriesQuery: >
        contextiq_requests_total{namespace!="",pod!=""}
      resources:
        overrides:
          namespace: { resource: namespace }
          pod:       { resource: pod }
      name:
        matches: "contextiq_requests_total"
        as:      "contextiq_requests_per_second"
      metricsQuery: >
        rate(contextiq_requests_total{<<.LabelMatchers>>}[2m])
```

---

### Production overrides

```yaml
# helm/charts/prometheus-adapter/values-prod.yaml
logLevel: 0
replicas: 2
metricsRelistInterval: 15s   # more frequent relist for faster HPA reaction in prod
```

---

### ArgoCD Application (adds prometheus-adapter to App-of-Apps)

```yaml
# argocd/apps/services/prometheus-adapter.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prometheus-adapter
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: contextiq
  source:
    repoURL:        https://prometheus-community.github.io/helm-charts
    chart:          prometheus-adapter
    targetRevision: "4.10.0"    # pin version for reproducibility
    helm:
      valueFiles:
        - values.yaml
        - values-prod.yaml
      # Values files are relative to the chart — pass via --values flags from Git
      # In ArgoCD, use a local chart wrapper:
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-observability
  syncPolicy:
    automated: { prune: true, selfHeal: true }
```

---

### Verification: query the custom metrics API

```bash
# Run after helm install to confirm contextiq_active_requests is visible
kubectl get --raw \
  "/apis/custom.metrics.k8s.io/v1beta1/namespaces/contextiq-agents/pods/*/contextiq_active_requests" \
  | python3 -m json.tool

# Expected output shape:
# {
#   "kind": "MetricValueList",
#   "items": [
#     {
#       "describedObject": { "kind": "Pod", "name": "agent-worker-abc123", ... },
#       "metricName": "contextiq_active_requests",
#       "value": "3"
#     },
#     ...
#   ]
# }
```

---

### NetworkPolicy: allow Prometheus Adapter → Prometheus scrape

```yaml
# k8s/network-policies/allow-rules/prometheus-adapter-to-prometheus.yaml
# Prometheus Adapter must be able to query Prometheus to derive custom metric values.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-adapter-to-prometheus
  namespace: contextiq-observability
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus-adapter
      ports:
        - { protocol: TCP, port: 9090 }
```

## Acceptance Criteria

- [ ] `kubectl api-resources | grep custom.metrics` shows `custom.metrics.k8s.io` registered — adapter is running (AC-2)
- [ ] `kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/contextiq-agents/pods/*/contextiq_active_requests"` returns a valid `MetricValueList` (AC-2)
- [ ] Prometheus Adapter pod logs show no errors querying Prometheus (AC-2)
- [ ] Two adapter replicas running for HA: `kubectl get pods -n contextiq-observability | grep adapter` shows 2 Running
- [ ] `metricsRelistInterval: 15s` in prod ensures metric names are refreshed fast enough for 30 s scale-up (AC-4)

## Dependencies

- TASK-US045-01 — `contextiq-observability` namespace must exist
- TASK-US045-02 — NetworkPolicy allow-rule for adapter → Prometheus added to base policy set
- US-036 TASK-US036-01 — `contextiq_active_requests` Gauge must be scraped by Prometheus before adapter can expose it
- TASK-US045-04 — ArgoCD App-of-Apps must include this Application

## Definition of Done

- [ ] `helm install prometheus-adapter prometheus-community/prometheus-adapter -n contextiq-observability -f values.yaml -f values-prod.yaml` succeeds
- [ ] `kubectl get --raw` custom metrics API call returns non-empty `MetricValueList`
- [ ] `helm lint helm/charts/prometheus-adapter/` passes
