# TASK-US046-01 — HPA and PDB for MCP Gateway (CPU-Based Scaling)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US046-01 |
| User Story | US-046 |
| Epic | EP-TECH-001 — Platform Infrastructure & Kubernetes |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Configure the `HorizontalPodAutoscaler` for the MCP Gateway service with a CPU utilization target of 60%, minimum 2 replicas, and maximum 10 replicas (AC-1, AC-3). Add a `PodDisruptionBudget` ensuring at least 2 replicas are always running during voluntary disruptions such as node drains and rolling upgrades (AC-5). Both objects are embedded as Helm chart templates in `helm/charts/mcp-gateway/` (AC-6) using the `hpa.yaml` and `pdb.yaml` templates scaffolded in TASK-US045-03, extended here with scale timing behaviour (AC-4).

## Implementation Details

**Technology:** Kubernetes 1.29+ `autoscaling/v2`, `policy/v1` PDB, Helm 3.15+

**File locations:**
- `helm/charts/mcp-gateway/templates/hpa.yaml` — HPA (extend scaffold from US-045)
- `helm/charts/mcp-gateway/templates/pdb.yaml` — PDB (extend scaffold from US-045)
- `helm/charts/mcp-gateway/values.yaml` — extend with scale timing fields
- `helm/charts/mcp-gateway/values-prod.yaml` — production overrides

---

### Updated `values.yaml` (add scale timing stanza)

```yaml
# helm/charts/mcp-gateway/values.yaml  (extend — add/replace hpa section)
hpa:
  enabled: true
  minReplicas: 2          # AC-1
  maxReplicas: 10         # AC-1
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60    # AC-3: target 60% CPU
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0     # AC-4: scale up immediately (< 30 s)
      policies:
        - type:          Pods
          value:         4              # add up to 4 pods per scaling event
          periodSeconds: 30             # AC-4: evaluated every 30 s
    scaleDown:
      stabilizationWindowSeconds: 300   # AC-4: 5-minute scale-down stabilisation window
      policies:
        - type:          Pods
          value:         1              # remove at most 1 pod per scaling event
          periodSeconds: 60

pdb:
  enabled: true
  minAvailable: 2   # AC-5: at least 2 Gateway pods always running
```

---

### HPA template (full — replaces scaffold)

```yaml
# helm/charts/mcp-gateway/templates/hpa.yaml
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

### PDB template (full — replaces scaffold)

```yaml
# helm/charts/mcp-gateway/templates/pdb.yaml
{{- if .Values.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "contextiq-common.fullname" . }}
  namespace: {{ .Values.namespace }}
  labels:
    {{- include "contextiq-common.labels" . | nindent 4 }}
spec:
  minAvailable: {{ .Values.pdb.minAvailable }}
  selector:
    matchLabels:
      {{- include "contextiq-common.selectorLabels" . | nindent 6 }}
{{- end }}
```

---

### Dev override (disable HPA/PDB for single-node dev)

```yaml
# helm/charts/mcp-gateway/values-dev.yaml  (extend)
hpa:
  enabled: false
pdb:
  enabled: false
```

---

### Production override

```yaml
# helm/charts/mcp-gateway/values-prod.yaml  (extend)
hpa:
  enabled: true
  minReplicas: 3      # prod: start at 3 for baseline HA
  maxReplicas: 10
pdb:
  enabled: true
  minAvailable: 2
```

## Acceptance Criteria

- [ ] `kubectl get hpa -n contextiq-gateway` shows `MIN PODS: 2`, `MAX PODS: 10`, `TARGETS: <x>%/60%` (AC-1, AC-3)
- [ ] `kubectl get pdb -n contextiq-gateway` shows `ALLOWED-DISRUPTIONS: ≥1` when 3+ pods running (AC-5)
- [ ] `kubectl drain <node>` cannot evict the last two Gateway pods simultaneously — PDB blocks it (AC-5)
- [ ] `helm template helm/charts/mcp-gateway/ -f values-dev.yaml | grep HorizontalPodAutoscaler` returns no output — HPA disabled in dev (AC-6)
- [ ] Scale-down `stabilizationWindowSeconds: 300` is visible in `kubectl describe hpa` (AC-4)

## Dependencies

- TASK-US045-01 — `contextiq-gateway` namespace must exist
- TASK-US045-03 — Helm chart scaffold (`hpa.yaml`, `pdb.yaml` templates exist)
- US-036 — MCP Gateway exposes CPU-based `resource.requests.cpu` for HPA metric source

## Definition of Done

- [ ] `helm lint helm/charts/mcp-gateway/` passes
- [ ] `kubectl get hpa release-name-mcp-gateway -n contextiq-gateway -o yaml` shows correct `behavior` stanza
- [ ] `kubectl describe pdb release-name-mcp-gateway -n contextiq-gateway` shows `Min Available: 2`
