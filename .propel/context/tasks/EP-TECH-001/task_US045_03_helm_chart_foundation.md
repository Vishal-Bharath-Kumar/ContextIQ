# TASK-US045-03 — Helm Chart Foundation: Parameterized Charts for All Services

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US045-03 |
| User Story | US-045 |
| Epic | EP-TECH-001 — Platform Infrastructure & Kubernetes |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | Done |

## Description

Define the Helm chart structure for all ContextIQ services (AC-2), using a shared `common` library chart that provides reusable template helpers (Deployment, Service, Ingress, HPA, PDB). Each service chart carries `values.yaml` (defaults) plus environment-specific overrides in `values-dev.yaml`, `values-staging.yaml`, and `values-prod.yaml`. Every chart includes a `/healthz` probe so `kubectl rollout status` converges only when all pods pass readiness (AC-5, AC-6). A single umbrella chart (`contextiq`) lists all service charts as dependencies for one-shot cluster bootstrap.

## Implementation Details

**Technology:** Helm 3.15+, Kubernetes 1.29+

**File locations (representative set — pattern repeated per service):**
- `helm/library/contextiq-common/` — shared library chart
- `helm/charts/mcp-gateway/` — MCP Gateway chart (canonical example)
- `helm/charts/agent-worker/`
- `helm/charts/admin-portal/`
- `helm/charts/keycloak/`
- `helm/charts/jaeger/`
- `helm/contextiq/Chart.yaml` — umbrella chart
- `helm/contextiq/values.yaml` — global defaults
- `helm/contextiq/values-dev.yaml`
- `helm/contextiq/values-staging.yaml`
- `helm/contextiq/values-prod.yaml`

---

### Common library chart structure

```
helm/library/contextiq-common/
├── Chart.yaml
└── templates/
    ├── _deployment.tpl   # reusable Deployment helper
    ├── _service.tpl      # reusable Service helper
    ├── _ingress.tpl      # reusable Ingress helper
    ├── _hpa.tpl          # reusable HPA helper
    └── _helpers.tpl      # name/label helpers
```

```yaml
# helm/library/contextiq-common/Chart.yaml
apiVersion: v2
name: contextiq-common
description: Shared Helm library for ContextIQ services
type: library
version: 0.1.0
```

```
{{- /* helm/library/contextiq-common/templates/_helpers.tpl */}}
{{- define "contextiq-common.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "contextiq-common.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | default "latest" | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: contextiq
{{- end }}

{{- define "contextiq-common.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

---

### MCP Gateway chart — canonical example

```
helm/charts/mcp-gateway/
├── Chart.yaml
├── values.yaml
├── values-dev.yaml
├── values-staging.yaml
├── values-prod.yaml
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    ├── ingress.yaml
    ├── hpa.yaml
    ├── pdb.yaml
    └── serviceaccount.yaml
```

```yaml
# helm/charts/mcp-gateway/Chart.yaml
apiVersion: v2
name: mcp-gateway
description: ContextIQ MCP Gateway — FastAPI + FastMCP service
type: application
version: 0.1.0
appVersion: "1.0.0"
dependencies:
  - name: contextiq-common
    version: "0.1.0"
    repository: "file://../../library/contextiq-common"
```

```yaml
# helm/charts/mcp-gateway/values.yaml
# AC-2: defaults (overridden per environment)
replicaCount: 2

image:
  repository: contextiq/mcp-gateway
  pullPolicy: IfNotPresent
  tag: ""       # overridden by CI with the git SHA

namespace: contextiq-gateway

service:
  type: ClusterIP
  port: 80
  targetPort: 8000

ingress:
  enabled: true
  className: nginx
  host: contextiq.internal
  path: /

resources:
  requests:
    cpu:    "250m"
    memory: "512Mi"
  limits:
    cpu:    "2"
    memory: "2Gi"

readinessProbe:
  httpGet:
    path: /healthz    # AC-6
    port: 8000
  initialDelaySeconds: 10
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
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 60

pdb:
  enabled: true
  minAvailable: 1

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

env:
  # All sensitive values come from Kubernetes Secrets injected via Vault Agent
  KEYCLOAK_URL:   "http://keycloak.contextiq-security.svc.cluster.local/auth"
  KEYCLOAK_REALM: "contextiq"
  OPA_URL:        "http://opa.contextiq-security.svc.cluster.local:8181"
  DATABASE_URL:   ""    # injected from Secret
  REDIS_URL:      ""    # injected from Secret
```

```yaml
# helm/charts/mcp-gateway/values-dev.yaml
# AC-2: dev overrides — relaxed probes, single replica, debug logging
replicaCount: 1
hpa:
  enabled: false
pdb:
  enabled: false
env:
  LOG_LEVEL: DEBUG
  KEYCLOAK_URL: "http://localhost:8080/auth"
```

```yaml
# helm/charts/mcp-gateway/values-staging.yaml
# AC-2: staging — mirrors prod topology at reduced scale
replicaCount: 2
hpa:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
env:
  LOG_LEVEL: INFO
```

```yaml
# helm/charts/mcp-gateway/values-prod.yaml
# AC-2: production — full HA, strict resource bounds
replicaCount: 3
hpa:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
env:
  LOG_LEVEL: WARNING
```

---

### Deployment template (uses common library)

```yaml
# helm/charts/mcp-gateway/templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "contextiq-common.fullname" . }}
  namespace: {{ .Values.namespace }}
  labels:
    {{- include "contextiq-common.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{- include "contextiq-common.selectorLabels" . | nindent 6 }}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    metadata:
      labels:
        {{- include "contextiq-common.selectorLabels" . | nindent 8 }}
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port:   "9000"
        prometheus.io/path:   "/metrics"
    spec:
      securityContext:
        {{- toYaml .Values.podSecurityContext | nindent 8 }}
      terminationGracePeriodSeconds: 30
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: {{ .Values.service.targetPort }}
              name: http
          envFrom:
            - secretRef:
                name: {{ include "contextiq-common.fullname" . }}-secrets
          env:
            {{- range $k, $v := .Values.env }}
            - name: {{ $k }}
              value: {{ $v | quote }}
            {{- end }}
          readinessProbe:
            {{- toYaml .Values.readinessProbe | nindent 12 }}
          livenessProbe:
            {{- toYaml .Values.livenessProbe | nindent 12 }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          securityContext:
            {{- toYaml .Values.containerSecurityContext | nindent 12 }}
```

---

### HPA template

```yaml
# helm/charts/mcp-gateway/templates/hpa.yaml
{{- if .Values.hpa.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "contextiq-common.fullname" . }}
  namespace: {{ .Values.namespace }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "contextiq-common.fullname" . }}
  minReplicas: {{ .Values.hpa.minReplicas }}
  maxReplicas: {{ .Values.hpa.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.hpa.targetCPUUtilizationPercentage }}
{{- end }}
```

---

### Umbrella chart

```yaml
# helm/contextiq/Chart.yaml
apiVersion: v2
name: contextiq
description: ContextIQ platform umbrella chart
type: application
version: 0.1.0
dependencies:
  - name: mcp-gateway
    version: "0.1.0"
    repository: "file://../charts/mcp-gateway"
  - name: agent-worker
    version: "0.1.0"
    repository: "file://../charts/agent-worker"
  - name: admin-portal
    version: "0.1.0"
    repository: "file://../charts/admin-portal"
  - name: keycloak
    version: "0.1.0"
    repository: "file://../charts/keycloak"
  - name: jaeger
    version: "0.1.0"
    repository: "file://../charts/jaeger"
  # ... remaining service charts
```

```yaml
# helm/contextiq/values-prod.yaml  (global production overrides)
global:
  imageRegistry: registry.contextiq.internal
  environment:   production
mcp-gateway:
  replicaCount: 3
agent-worker:
  replicaCount: 4
```

## Acceptance Criteria

- [x] `helm lint helm/charts/mcp-gateway/` passes with no errors (AC-2)
- [x] `helm template helm/charts/mcp-gateway/ -f values-prod.yaml` renders a Deployment with `replicaCount: 3` (AC-2)
- [x] All rendered Deployment specs include both `readinessProbe` and `livenessProbe` targeting `/healthz` (AC-6)
- [x] `helm template` with `values-dev.yaml` disables HPA and PDB (AC-2)
- [x] HPA template is not rendered when `hpa.enabled: false` (dev override) (AC-2)
- [x] `containerSecurityContext` includes `readOnlyRootFilesystem: true`, `runAsNonRoot: true`, `capabilities.drop: ["ALL"]` in every rendered Deployment (OWASP A05)

## Dependencies

- TASK-US045-01 — namespace names referenced in chart `values.yaml`
- Helm 3.15+ installed in CI pipeline (US-046 TASK-US046 and ArgoCD task will consume these charts)

## Definition of Done

- [x] `helm lint` passes for all 5+ service charts
- [x] `helm install --dry-run contextiq helm/contextiq/ -f values-staging.yaml` succeeds
- [x] CI pipeline renders templates for all three environments and `kubectl apply --dry-run=server` validates them
