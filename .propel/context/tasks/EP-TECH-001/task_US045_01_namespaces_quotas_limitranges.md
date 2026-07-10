# TASK-US045-01 — Namespace Definitions, ResourceQuota, and LimitRange

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US045-01 |
| User Story | US-045 |
| Epic | EP-TECH-001 — Platform Infrastructure & Kubernetes |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Create the seven canonical ContextIQ namespaces (AC-1) and apply `ResourceQuota` and `LimitRange` objects to each one (AC-3). Namespaces map to logical domains: data stores, AI agent workers, the MCP gateway, the admin portal, observability tooling, security services (Keycloak, OPA), and shared infrastructure (MinIO, Kafka). Resource budgets are sized for production traffic at Phase 2 scale with headroom for autoscaling (US-046).

## Implementation Details

**Technology:** Kubernetes 1.29+, Kustomize

**File locations:**
- `k8s/namespaces/namespaces.yaml` — all 7 Namespace objects
- `k8s/namespaces/resource-quotas.yaml` — one `ResourceQuota` per namespace
- `k8s/namespaces/limit-ranges.yaml` — one `LimitRange` per namespace
- `k8s/namespaces/kustomization.yaml`

---

### Namespaces

```yaml
# k8s/namespaces/namespaces.yaml
# AC-1: seven canonical ContextIQ namespaces
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-data
  labels:
    app.kubernetes.io/part-of: contextiq
    team: platform
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-agents
  labels:
    app.kubernetes.io/part-of: contextiq
    team: platform
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-gateway
  labels:
    app.kubernetes.io/part-of: contextiq
    team: platform
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-admin
  labels:
    app.kubernetes.io/part-of: contextiq
    team: platform
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-observability
  labels:
    app.kubernetes.io/part-of: contextiq
    team: platform
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-security
  labels:
    app.kubernetes.io/part-of: contextiq
    team: platform
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-infra
  labels:
    app.kubernetes.io/part-of: contextiq
    team: platform
```

---

### ResourceQuota (one per namespace)

```yaml
# k8s/namespaces/resource-quotas.yaml
# Sizing rationale:
#   contextiq-agents: highest CPU/memory — LangGraph workers + LLM calls
#   contextiq-gateway: medium — FastAPI + OTel middleware
#   contextiq-data: medium — PostgreSQL + Redis + Qdrant resident memory
#   contextiq-infra: medium — MinIO + Kafka brokers
#   contextiq-security: small — Keycloak (2 replicas) + OPA
#   contextiq-admin: small — nginx SPA + Admin API
#   contextiq-observability: small — Prometheus + Grafana + Jaeger

apiVersion: v1
kind: ResourceQuota
metadata:
  name: quota
  namespace: contextiq-agents
spec:
  hard:
    requests.cpu:    "16"
    requests.memory: "32Gi"
    limits.cpu:      "32"
    limits.memory:   "64Gi"
    pods:            "40"
    services:        "20"
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: quota
  namespace: contextiq-gateway
spec:
  hard:
    requests.cpu:    "8"
    requests.memory: "16Gi"
    limits.cpu:      "16"
    limits.memory:   "32Gi"
    pods:            "20"
    services:        "10"
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: quota
  namespace: contextiq-data
spec:
  hard:
    requests.cpu:    "8"
    requests.memory: "32Gi"
    limits.cpu:      "16"
    limits.memory:   "64Gi"
    pods:            "20"
    services:        "15"
    persistentvolumeclaims: "20"
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: quota
  namespace: contextiq-infra
spec:
  hard:
    requests.cpu:    "8"
    requests.memory: "16Gi"
    limits.cpu:      "16"
    limits.memory:   "32Gi"
    pods:            "20"
    services:        "10"
    persistentvolumeclaims: "15"
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: quota
  namespace: contextiq-security
spec:
  hard:
    requests.cpu:    "4"
    requests.memory: "8Gi"
    limits.cpu:      "8"
    limits.memory:   "16Gi"
    pods:            "15"
    services:        "10"
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: quota
  namespace: contextiq-admin
spec:
  hard:
    requests.cpu:    "2"
    requests.memory: "4Gi"
    limits.cpu:      "4"
    limits.memory:   "8Gi"
    pods:            "10"
    services:        "10"
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: quota
  namespace: contextiq-observability
spec:
  hard:
    requests.cpu:    "4"
    requests.memory: "8Gi"
    limits.cpu:      "8"
    limits.memory:   "16Gi"
    pods:            "15"
    services:        "10"
    persistentvolumeclaims: "10"
```

---

### LimitRange (default container limits per namespace)

```yaml
# k8s/namespaces/limit-ranges.yaml
# AC-3: LimitRange ensures every container has a bounded resource footprint
# even when individual Deployment specs omit explicit limits.

apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: contextiq-agents
spec:
  limits:
    - type: Container
      default:          { cpu: "2",    memory: "4Gi" }
      defaultRequest:   { cpu: "500m", memory: "1Gi" }
      max:              { cpu: "8",    memory: "16Gi" }
      min:              { cpu: "100m", memory: "128Mi" }
---
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: contextiq-gateway
spec:
  limits:
    - type: Container
      default:          { cpu: "1",    memory: "2Gi" }
      defaultRequest:   { cpu: "250m", memory: "512Mi" }
      max:              { cpu: "4",    memory: "8Gi" }
      min:              { cpu: "100m", memory: "128Mi" }
---
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: contextiq-data
spec:
  limits:
    - type: Container
      default:          { cpu: "1",    memory: "4Gi" }
      defaultRequest:   { cpu: "250m", memory: "1Gi" }
      max:              { cpu: "8",    memory: "32Gi" }
      min:              { cpu: "100m", memory: "256Mi" }
---
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: contextiq-infra
spec:
  limits:
    - type: Container
      default:          { cpu: "1",    memory: "2Gi" }
      defaultRequest:   { cpu: "250m", memory: "512Mi" }
      max:              { cpu: "8",    memory: "16Gi" }
      min:              { cpu: "100m", memory: "256Mi" }
---
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: contextiq-security
spec:
  limits:
    - type: Container
      default:          { cpu: "500m", memory: "1Gi" }
      defaultRequest:   { cpu: "250m", memory: "512Mi" }
      max:              { cpu: "4",    memory: "8Gi" }
      min:              { cpu: "100m", memory: "128Mi" }
---
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: contextiq-admin
spec:
  limits:
    - type: Container
      default:          { cpu: "250m", memory: "512Mi" }
      defaultRequest:   { cpu: "100m", memory: "128Mi" }
      max:              { cpu: "2",    memory: "4Gi" }
      min:              { cpu: "50m",  memory: "64Mi" }
---
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: contextiq-observability
spec:
  limits:
    - type: Container
      default:          { cpu: "500m", memory: "2Gi" }
      defaultRequest:   { cpu: "250m", memory: "512Mi" }
      max:              { cpu: "4",    memory: "8Gi" }
      min:              { cpu: "100m", memory: "256Mi" }
```

---

### Kustomization

```yaml
# k8s/namespaces/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - namespaces.yaml
  - resource-quotas.yaml
  - limit-ranges.yaml
```

## Acceptance Criteria

- [ ] `kubectl get namespaces | grep contextiq` returns exactly 7 namespaces (AC-1)
- [ ] `kubectl get resourcequota -A | grep contextiq` returns 7 quota objects (AC-3)
- [ ] `kubectl get limitrange -A | grep contextiq` returns 7 limit-range objects (AC-3)
- [ ] A Pod deployed without explicit `resources:` block in `contextiq-agents` still has default limits applied by the LimitRange (AC-3)
- [ ] `kubectl apply -k k8s/namespaces/` is idempotent — re-applying does not error on existing objects

## Dependencies

- EP-TECH-001 (this is the foundational task — no upstream platform dependencies)
- Kubernetes 1.29+ cluster with `kubectl` access

## Definition of Done

- [ ] `kubectl apply -k k8s/namespaces/` completes without error in staging cluster
- [ ] `kubectl describe resourcequota quota -n contextiq-agents` shows correct hard limits
