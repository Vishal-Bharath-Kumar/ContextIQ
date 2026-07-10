# TASK-US046-03 — HPA for Agent Worker on Custom Metric `contextiq_active_requests`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US046-03 |
| User Story | US-046 |
| Epic | EP-TECH-001 — Platform Infrastructure & Kubernetes |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Configure the `HorizontalPodAutoscaler` for `contextiq-agent-worker` with min 2 and max 20 replicas, scaling on the custom metric `contextiq_active_requests` (AC-1, AC-2) sourced from the Prometheus Adapter (TASK-US046-02). The target value is 5 active requests per pod — when the average across existing pods exceeds this threshold, new pods are added. Scale-up is triggered within 30 s; scale-down uses a 5-minute stabilization window (AC-4). The HPA is embedded in the `helm/charts/agent-worker/` Helm chart with environment-specific value overrides (AC-6).

## Implementation Details

**Technology:** Kubernetes 1.29+ `autoscaling/v2` custom metrics, Helm 3.15+

**File locations:**
- `helm/charts/agent-worker/Chart.yaml`
- `helm/charts/agent-worker/values.yaml`
- `helm/charts/agent-worker/values-dev.yaml`
- `helm/charts/agent-worker/values-staging.yaml`
- `helm/charts/agent-worker/values-prod.yaml`
- `helm/charts/agent-worker/templates/hpa.yaml`
- `helm/charts/agent-worker/templates/deployment.yaml`

---

### Agent Worker Helm chart stub

```yaml
# helm/charts/agent-worker/Chart.yaml
apiVersion: v2
name: agent-worker
description: ContextIQ LangGraph Agent Worker
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
# helm/charts/agent-worker/values.yaml
replicaCount: 2

image:
  repository: contextiq/agent-worker
  pullPolicy: IfNotPresent
  tag: ""

namespace: contextiq-agents

service:
  type: ClusterIP
  port: 80
  targetPort: 8000

resources:
  requests:
    cpu:    "500m"
    memory: "1Gi"
  limits:
    cpu:    "4"
    memory: "8Gi"

readinessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 15
  periodSeconds: 10
  failureThreshold: 3

livenessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 30
  failureThreshold: 5

hpa:
  enabled: true
  minReplicas: 2      # AC-1
  maxReplicas: 20     # AC-1
  # AC-2: scale on custom metric contextiq_active_requests (per-pod target)
  customMetric:
    enabled: true
    name: contextiq_active_requests          # matches rule name in Prometheus Adapter
    targetAverageValue: "5"                  # scale up when avg active reqs/pod > 5
  # AC-3: keep CPU fallback so HPA still scales during Prometheus Adapter outage
  cpuFallback:
    enabled: true
    targetAverageUtilization: 70
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type:          Pods
          value:         5              # add up to 5 pods per event (agent workers are heavyweight)
          periodSeconds: 30             # AC-4: evaluated every 30 s
    scaleDown:
      stabilizationWindowSeconds: 300   # AC-4: 5-minute scale-down window
      policies:
        - type:          Pods
          value:         2
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

### HPA template with dual-metric (custom + CPU fallback)

```yaml
# helm/charts/agent-worker/templates/hpa.yaml
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
    {{- if .Values.hpa.customMetric.enabled }}
    # AC-2: primary scale signal — contextiq_active_requests per pod
    - type: Pods
      pods:
        metric:
          name: {{ .Values.hpa.customMetric.name }}
        target:
          type:         AverageValue
          averageValue: {{ .Values.hpa.customMetric.targetAverageValue }}
    {{- end }}
    {{- if .Values.hpa.cpuFallback.enabled }}
    # CPU fallback — HPA takes the MAX of all metric signals, so this fires
    # if the custom metric is unavailable and CPU is high
    - type: Resource
      resource:
        name: cpu
        target:
          type:               Utilization
          averageUtilization: {{ .Values.hpa.cpuFallback.targetAverageUtilization }}
    {{- end }}
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
# helm/charts/agent-worker/values-dev.yaml
replicaCount: 1
hpa:
  enabled: false   # single pod in dev — no auto-scaling overhead
```

```yaml
# helm/charts/agent-worker/values-staging.yaml
replicaCount: 2
hpa:
  enabled: true
  minReplicas: 2
  maxReplicas: 8    # reduced max in staging to control cost
  customMetric:
    targetAverageValue: "5"
```

```yaml
# helm/charts/agent-worker/values-prod.yaml
replicaCount: 3
hpa:
  enabled: true
  minReplicas: 3     # prod baseline higher for warm capacity
  maxReplicas: 20
  customMetric:
    targetAverageValue: "5"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Pods
          value: 5
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
```

---

### ArgoCD Application

```yaml
# argocd/apps/services/agent-worker.yaml  (extend existing file)
# (no change needed — chart path already set; ArgoCD picks up new hpa.yaml template)
```

## Acceptance Criteria

- [ ] `kubectl get hpa -n contextiq-agents` shows `MIN PODS: 2`, `MAX PODS: 20`, metric source `contextiq_active_requests` (AC-1, AC-2)
- [ ] HPA `TARGETS` column shows `<current>/<5>` (AverageValue custom metric) (AC-2)
- [ ] When `contextiq_active_requests` average exceeds 5 per pod, HPA adds pods within 30 s (AC-4)
- [ ] After load drops, HPA waits 300 s before removing pods (AC-4)
- [ ] CPU fallback metric is also present in HPA spec — `kubectl describe hpa` lists both metrics (AC-2)
- [ ] `helm template -f values-dev.yaml | grep HPA` returns empty — HPA disabled in dev (AC-6)

## Dependencies

- TASK-US046-02 — Prometheus Adapter must expose `contextiq_active_requests` on `custom.metrics.k8s.io` before this HPA becomes functional
- TASK-US045-01 — `contextiq-agents` namespace must exist
- TASK-US045-03 — `contextiq-common` library chart and label helpers referenced

## Definition of Done

- [ ] `helm lint helm/charts/agent-worker/` passes
- [ ] `kubectl describe hpa -n contextiq-agents` shows both Pods metric (`contextiq_active_requests`) and Resource metric (`cpu`) listed
- [ ] Staging load test (TASK-US046-05) drives `contextiq_active_requests` above threshold and confirms scale-up within 30 s
