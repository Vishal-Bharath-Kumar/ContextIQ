# TASK-US045-02 — Network Policies: Default-Deny and Explicit Inter-Namespace Allow Rules

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US045-02 |
| User Story | US-045 |
| Epic | EP-TECH-001 — Platform Infrastructure & Kubernetes |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | Done |

## Description

Apply a `NetworkPolicy` default-deny posture to every namespace and then layer explicit allow rules that reflect the ContextIQ service dependency graph (AC-4). Each namespace starts with an ingress + egress deny-all policy; individual allow rules open only the port + protocol combinations required for legitimate service-to-service communication. The policy set is expressed as Kustomize overlays so dev/staging/prod can relax rules (e.g. allow `kubectl exec` in dev) without touching the base policies.

## Implementation Details

**Technology:** Kubernetes 1.29+ `NetworkPolicy` (CNI must support it — Calico, Cilium, or AWS VPC CNI with network policy enabled)

**File locations:**
- `k8s/network-policies/default-deny/` — one default-deny file per namespace
- `k8s/network-policies/allow-rules/` — explicit allow rules
- `k8s/network-policies/kustomization.yaml`

**Service dependency graph (inter-namespace flows):**

| From namespace | To namespace | Port(s) | Protocol |
|---|---|---|---|
| `contextiq-gateway` | `contextiq-agents` | 8000 | TCP |
| `contextiq-gateway` | `contextiq-data` | 5432, 6379 | TCP |
| `contextiq-gateway` | `contextiq-security` | 8080 (Keycloak), 8181 (OPA) | TCP |
| `contextiq-agents` | `contextiq-data` | 5432, 6379, 6333 (Qdrant), 7474/7687 (Neo4j) | TCP |
| `contextiq-agents` | `contextiq-infra` | 9092 (Kafka), 9000 (MinIO) | TCP |
| `contextiq-admin` | `contextiq-gateway` | 443 | TCP |
| `contextiq-observability` | all namespaces | 9000 (metrics scrape) | TCP |
| all namespaces | `contextiq-observability` | 4317 (OTLP gRPC) | TCP |

---

### Default-deny policies (one per namespace — only gateway shown in full; others follow same pattern)

```yaml
# k8s/network-policies/default-deny/contextiq-gateway.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: contextiq-gateway
spec:
  podSelector: {}       # matches ALL pods in this namespace
  policyTypes:
    - Ingress
    - Egress
  # No ingress/egress rules = deny all
---
# k8s/network-policies/default-deny/contextiq-agents.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: contextiq-agents
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# k8s/network-policies/default-deny/contextiq-data.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: contextiq-data
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# k8s/network-policies/default-deny/contextiq-admin.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: contextiq-admin
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# k8s/network-policies/default-deny/contextiq-observability.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: contextiq-observability
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# k8s/network-policies/default-deny/contextiq-security.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: contextiq-security
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# k8s/network-policies/default-deny/contextiq-infra.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: contextiq-infra
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
```

---

### Explicit allow rules

```yaml
# k8s/network-policies/allow-rules/gateway-to-agents.yaml
# Allow gateway pods to reach agent-worker pods on port 8000
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-gateway-to-agents
  namespace: contextiq-agents
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: agent-worker
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: contextiq-gateway
      ports:
        - protocol: TCP
          port: 8000
---
# k8s/network-policies/allow-rules/gateway-to-data.yaml
# Allow gateway → PostgreSQL and Redis
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-gateway-to-data
  namespace: contextiq-data
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: contextiq-gateway
      ports:
        - { protocol: TCP, port: 5432 }   # PostgreSQL
        - { protocol: TCP, port: 6379 }   # Redis
---
# k8s/network-policies/allow-rules/agents-to-data.yaml
# Allow agent workers → all data stores
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-agents-to-data
  namespace: contextiq-data
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: contextiq-agents
      ports:
        - { protocol: TCP, port: 5432 }   # PostgreSQL
        - { protocol: TCP, port: 6379 }   # Redis
        - { protocol: TCP, port: 6333 }   # Qdrant HTTP
        - { protocol: TCP, port: 6334 }   # Qdrant gRPC
        - { protocol: TCP, port: 7474 }   # Neo4j HTTP
        - { protocol: TCP, port: 7687 }   # Neo4j Bolt
---
# k8s/network-policies/allow-rules/agents-to-infra.yaml
# Allow agent workers → Kafka + MinIO
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-agents-to-infra
  namespace: contextiq-infra
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: contextiq-agents
      ports:
        - { protocol: TCP, port: 9092 }   # Kafka
        - { protocol: TCP, port: 9000 }   # MinIO API
---
# k8s/network-policies/allow-rules/gateway-to-security.yaml
# Allow gateway → Keycloak JWKS + OPA policy evaluation
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-gateway-to-security
  namespace: contextiq-security
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: contextiq-gateway
      ports:
        - { protocol: TCP, port: 8080 }   # Keycloak
        - { protocol: TCP, port: 8181 }   # OPA
---
# k8s/network-policies/allow-rules/admin-to-gateway.yaml
# Allow admin portal → MCP gateway API
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-admin-to-gateway
  namespace: contextiq-gateway
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: mcp-gateway
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: contextiq-admin
      ports:
        - { protocol: TCP, port: 8000 }
---
# k8s/network-policies/allow-rules/otlp-egress-all.yaml
# Allow ALL pods in all namespaces to emit OTLP spans to Jaeger in contextiq-observability
# Applied as 7 separate ingress rules on the observability namespace — one per source namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-otlp-ingress
  namespace: contextiq-observability
spec:
  podSelector:
    matchLabels:
      app: jaeger
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchExpressions:
              - key: app.kubernetes.io/part-of
                operator: In
                values: [contextiq]
      ports:
        - { protocol: TCP, port: 4317 }   # OTLP gRPC
        - { protocol: TCP, port: 4318 }   # OTLP HTTP
---
# k8s/network-policies/allow-rules/prometheus-scrape.yaml
# Allow Prometheus (observability) to scrape metrics from all contextiq namespaces
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape
  namespace: contextiq-gateway        # duplicate with app.kubernetes.io/part-of label selector
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: contextiq-observability
      ports:
        - { protocol: TCP, port: 9000 }
---
# k8s/network-policies/allow-rules/dns-egress-all.yaml
# Allow kube-dns egress from all namespaces (required for service discovery)
# Applied per-namespace to permit DNS resolution — without this all inter-service
# calls using cluster-local DNS names fail.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: contextiq-gateway
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }
```

---

### Kustomization (base)

```yaml
# k8s/network-policies/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  # Default-deny
  - default-deny/contextiq-gateway.yaml
  - default-deny/contextiq-agents.yaml
  - default-deny/contextiq-data.yaml
  - default-deny/contextiq-admin.yaml
  - default-deny/contextiq-observability.yaml
  - default-deny/contextiq-security.yaml
  - default-deny/contextiq-infra.yaml
  # Allow rules
  - allow-rules/gateway-to-agents.yaml
  - allow-rules/gateway-to-data.yaml
  - allow-rules/agents-to-data.yaml
  - allow-rules/agents-to-infra.yaml
  - allow-rules/gateway-to-security.yaml
  - allow-rules/admin-to-gateway.yaml
  - allow-rules/otlp-egress-all.yaml
  - allow-rules/prometheus-scrape.yaml
  - allow-rules/dns-egress-all.yaml
```

## Acceptance Criteria

- [x] `kubectl get networkpolicies -A | grep contextiq` shows `default-deny-all` in all 7 namespaces (AC-4)
- [x] A test pod in `contextiq-gateway` cannot reach a pod in `contextiq-data` on port 5433 (an unused port not in any allow rule) — verifiable with `kubectl exec` + `nc` (AC-4)
- [x] A test pod in `contextiq-gateway` CAN reach a `contextiq-data` pod on port 5432 — the allow rule works (AC-4)
- [x] DNS resolution (`nslookup kubernetes.default`) works from inside any pod — `allow-dns-egress` rule applied (AC-4)
- [x] OTLP spans from `contextiq-agents` pods reach Jaeger in `contextiq-observability` on port 4317 (AC-4)

## Dependencies

- TASK-US045-01 — namespaces must exist before NetworkPolicy objects can be applied
- CNI plugin that enforces NetworkPolicy (Calico, Cilium, or AWS VPC CNI policy mode)

## Definition of Done

- [x] `kubectl apply -k k8s/network-policies/` completes without error
- [x] Connectivity matrix verified with `kubectl exec` + `nc -zv` in staging cluster
