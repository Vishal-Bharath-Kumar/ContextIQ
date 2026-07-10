# TASK-US046-04 — HPA for Indexing Service and Helm Chart Values Integration

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US046-04 |
| User Story | US-046 |
| Epic | EP-TECH-001 — Platform Infrastructure & Kubernetes |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Configure the `HorizontalPodAutoscaler` for the Indexing Service with min 1 and max 5 replicas (AC-1), scaling on CPU utilization (target 70%). Apply the same scale timing as the other services — scale-up within 30 s, scale-down stabilization window of 5 minutes (AC-4). Embed the HPA in `helm/charts/indexing-service/` following the same pattern as the gateway and agent-worker charts, completing the three-service HPA suite (AC-6). Also provide a unified `helm/contextiq/values-hpa-summary.yaml` that documents all HPA targets in one place for operator reference.

## Implementation Details

**Technology:** Kubernetes 1.29+ `autoscaling/v2`, Helm 3.15+

**File locations:**
- `helm/charts/indexing-service/Chart.yaml`
- `helm/charts/indexing-service/values.yaml`
- `helm/charts/indexing-service/values-dev.yaml`
- `helm/charts/indexing-service/values-staging.yaml`
- `helm/charts/indexing-service/values-prod.yaml`
- `helm/charts/indexing-service/templates/hpa.yaml`
- `helm/charts/indexing-service/templates/deployment.yaml`
- `helm/contextiq/values-hpa-summary.yaml` — operator reference (not applied to cluster)

---

### Indexing Service chart stub

```yaml
# helm/charts/indexing-service/Chart.yaml
apiVersion: v2
name: indexing-service
description: ContextIQ Indexing Service — Kafka consumer + embedding pipeline
type: application
version: 0.1.0
appVersion: "1.0.0"
dependencies:
  - name: contextiq-common
    version: "0.1.0"
    repository: "file://../../library/contextiq-common"
```

---

### `values.yaml`

```yaml
# helm/charts/indexing-service/values.yaml
replicaCount: 1

image:
  repository: contextiq/indexing-service
  pullPolicy: IfNotPresent
  tag: ""

namespace: contextiq-agents   # indexing runs in the agents namespace alongside workers

service:
  type: ClusterIP
  port: 80
  targetPort: 8000

resources:
  # Indexing is CPU-bound (embedding inference) — generous CPU allocation
  requests:
    cpu:    "500m"
    memory: "1Gi"
  limits:
    cpu:    "4"
    memory: "4Gi"

readinessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 20
  periodSeconds: 10
  failureThreshold: 3

livenessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 40
  periodSeconds: 30
  failureThreshold: 5

hpa:
  enabled: true
  minReplicas: 1      # AC-1: indexing can run on a single pod at rest
  maxReplicas: 5      # AC-1
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70    # embedding is CPU-intensive; 70% is sustainable
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type:          Pods
          value:         2           # add 2 pods per event (indexing backlog drains quickly)
          periodSeconds: 30          # AC-4: 30 s evaluation window
    scaleDown:
      stabilizationWindowSeconds: 300   # AC-4: 5-minute stabilisation window
      policies:
        - type:          Pods
          value:         1
          periodSeconds: 60

podSecurityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault

containerSecurityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem:   true
  runAsNonRoot:             true
  runAsUser:                1000
  capabilities:
    drop: ["ALL"]
```

---

### HPA template (identical structure to agent-worker, CPU-only)

```yaml
# helm/charts/indexing-service/templates/hpa.yaml
{{- if .Values.hpa.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "contextiq-common.fullname" . }}
  namespace: {{ .Values.namespace }}
  labels:
    {{- include "contextiq-common.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "contextiq-common.fullname" . }}
  minReplicas: {{ .Values.hpa.minReplicas }}
  maxReplicas: {{ .Values.hpa.maxReplicas }}
  metrics:
    {{- toYaml .Values.hpa.metrics | nindent 4 }}
  behavior:
    scaleUp:
      stabilizationWindowSeconds: {{ .Values.hpa.behavior.scaleUp.stabilizationWindowSeconds }}
      policies:
        {{- toYaml .Values.hpa.behavior.scaleUp.policies | nindent 8 }}
    scaleDown:
      stabilizationWindowSeconds: {{ .Values.hpa.behavior.scaleDown.stabilizationWindowSeconds }}
      policies:
        {{- toYaml .Values.hpa.behavior.scaleDown.policies | nindent 8 }}
{{- end }}
```

---

### Environment overrides

```yaml
# helm/charts/indexing-service/values-dev.yaml
hpa:
  enabled: false
```

```yaml
# helm/charts/indexing-service/values-staging.yaml
hpa:
  enabled: true
  minReplicas: 1
  maxReplicas: 3
```

```yaml
# helm/charts/indexing-service/values-prod.yaml
hpa:
  enabled: true
  minReplicas: 2      # keep at least 2 warm in prod for throughput ≥ 1 000 chunks/min (US-027 AC-5)
  maxReplicas: 5
```

---

### ArgoCD Application for Indexing Service

```yaml
# argocd/apps/services/indexing-service.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: indexing-service
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://github.com/your-org/contextiq.git
    targetRevision: HEAD
    path:           helm/charts/indexing-service
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-agents
  syncPolicy:
    automated: { prune: true, selfHeal: true }
  ignoreDifferences:
    - group: apps
      kind:  Deployment
      jsonPointers: [/spec/replicas]
```

---

### HPA summary reference document

```yaml
# helm/contextiq/values-hpa-summary.yaml
# OPERATOR REFERENCE — not applied to the cluster.
# Single view of all HPA targets across the three autoscaled services.
# Update this file whenever HPA thresholds change in individual chart values.

hpa_summary:
  # AC-1: three services, their min/max, and primary metric
  - service:     mcp-gateway
    namespace:   contextiq-gateway
    min_replicas: 2
    max_replicas: 10
    primary_metric: cpu
    target:         "60% CPU utilization"
    scale_up_window_s:   0
    scale_down_window_s: 300    # AC-4

  - service:     agent-worker
    namespace:   contextiq-agents
    min_replicas: 2
    max_replicas: 20
    primary_metric: contextiq_active_requests (custom)
    target:         "5 active requests per pod average"
    scale_up_window_s:   0
    scale_down_window_s: 300    # AC-4

  - service:     indexing-service
    namespace:   contextiq-agents
    min_replicas: 1
    max_replicas: 5
    primary_metric: cpu
    target:         "70% CPU utilization"
    scale_up_window_s:   0
    scale_down_window_s: 300    # AC-4

pdb_summary:
  - service:   mcp-gateway
    namespace: contextiq-gateway
    min_available: 2    # AC-5
```

## Acceptance Criteria

- [ ] `kubectl get hpa -n contextiq-agents indexing-service` shows `MIN PODS: 1`, `MAX PODS: 5`, target CPU 70% (AC-1)
- [ ] `kubectl describe hpa indexing-service -n contextiq-agents` shows `stabilizationWindowSeconds: 300` for scale-down (AC-4)
- [ ] `helm template -f values-prod.yaml` renders `minReplicas: 2` for indexing-service in prod (AC-6)
- [ ] `helm template -f values-dev.yaml | grep HPA` returns empty (AC-6)
- [ ] `values-hpa-summary.yaml` lists all three services with correct min/max replicas and timing values (AC-1, AC-4)

## Dependencies

- TASK-US045-01 — `contextiq-agents` namespace
- TASK-US045-03 — `contextiq-common` library chart
- TASK-US045-04 — ArgoCD App-of-Apps (`argocd/apps/services/indexing-service.yaml` added)
- US-027 — Indexing Service Deployment exists and exposes `/healthz`

## Definition of Done

- [ ] `helm lint helm/charts/indexing-service/` passes
- [ ] ArgoCD shows `indexing-service` Application as `Synced / Healthy`
- [ ] Three HPAs confirmed in staging: `kubectl get hpa -A | grep contextiq`
