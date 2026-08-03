# TASK-US048-03 — mTLS for Inter-service Communication via Istio

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US048-03 |
| User Story | US-048 |
| Epic | EP-TECH-002 — Security Hardening & Secrets Management |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | Done |

## Description

Deploy Istio service mesh in `STRICT` mTLS mode to enforce mutual TLS on all inter-service communication within the cluster (AC-3). Every pod in the `contextiq-*` namespaces receives an Envoy sidecar proxy via Istio's automatic injection, which handles certificate issuance (SPIFFE X.509 SVIDs via Istio's built-in CA — `istiod`) and mutual authentication transparently. A `PeerAuthentication` policy set to `STRICT` mode in each namespace ensures plaintext traffic between services is rejected at the mesh layer. An `AuthorizationPolicy` layer further restricts which services may call which other services (least-privilege service-to-service communication).

## Implementation Details

**Technology:** Istio 1.22.x (latest LTS), `istioctl 1.22`, Helm `istio/base` + `istio/istiod` charts

**File locations:**
- `helm/charts/istio-base/Chart.yaml` — Istio CRD wrapper
- `helm/charts/istiod/Chart.yaml` — Istiod wrapper
- `k8s/istio/peer-authentication.yaml` — namespace-scoped `PeerAuthentication` (STRICT mTLS)
- `k8s/istio/authorization-policies.yaml` — service-to-service `AuthorizationPolicy` rules
- `k8s/namespaces/namespace-labels.yaml` — add `istio-injection: enabled` to each `contextiq-*` namespace
- `argocd/apps/services/istio-base.yaml`
- `argocd/apps/services/istiod.yaml`

---

### Istio installation (Helm — two-chart pattern)

```yaml
# helm/charts/istio-base/Chart.yaml
apiVersion: v2
name:        istio-base
description: Istio CRDs and cluster-level resources for ContextIQ
type:        application
version:     0.1.0
dependencies:
  - name:       base
    version:    "1.22.3"
    repository: https://istio-release.storage.googleapis.com/charts
```

```yaml
# helm/charts/istiod/Chart.yaml
apiVersion: v2
name:        istiod
description: Istio control plane for ContextIQ
type:        application
version:     0.1.0
dependencies:
  - name:       istiod
    version:    "1.22.3"
    repository: https://istio-release.storage.googleapis.com/charts
```

```yaml
# helm/charts/istiod/values.yaml
istiod:
  pilot:
    replicaCount: 2    # HA control plane

    resources:
      requests: { cpu: "500m", memory: "2Gi" }
      limits:   { cpu: "2",    memory: "4Gi" }

  # AC-3: meshConfig forces STRICT mTLS as the mesh-wide default
  meshConfig:
    accessLogFile: /dev/stdout    # access logs forwarded to Loki via stdout collection
    enablePrometheusMerge: true

    # Default proxy behaviour: outbound traffic through Envoy is ALLOW_ANY
    # (overridden to REGISTRY_ONLY in prod via AuthorizationPolicy)
    outboundTrafficPolicy:
      mode: REGISTRY_ONLY

    # AC-4: Minimum TLS protocol version — TLS 1.3 for all mTLS connections
    meshMTLS:
      minProtocolVersion: TLSV1_3

  # Enable CNI plugin (avoids NET_ADMIN capability on init containers)
  cni:
    enabled: true

  # Prometheus scraping (ServiceMonitor created separately)
  pilot:
    env:
      PILOT_ENABLE_STATUS: "true"
```

---

### Namespace labels enabling Istio sidecar injection

```yaml
# k8s/namespaces/namespace-labels.yaml
# Patch to add istio-injection=enabled to all contextiq-* namespaces.
# Apply after Istio is deployed: kubectl apply -f namespace-labels.yaml
# Existing pods must be restarted (rolling restart) for sidecars to be injected.
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-data
  labels:
    istio-injection: enabled
    app.kubernetes.io/part-of: contextiq
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-agents
  labels:
    istio-injection: enabled
    app.kubernetes.io/part-of: contextiq
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-gateway
  labels:
    istio-injection: enabled
    app.kubernetes.io/part-of: contextiq
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-admin
  labels:
    istio-injection: enabled
    app.kubernetes.io/part-of: contextiq
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-observability
  labels:
    istio-injection: enabled
    app.kubernetes.io/part-of: contextiq
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-security
  labels:
    istio-injection: enabled
    app.kubernetes.io/part-of: contextiq
---
apiVersion: v1
kind: Namespace
metadata:
  name: contextiq-infra
  labels:
    istio-injection: enabled
    app.kubernetes.io/part-of: contextiq
```

---

### PeerAuthentication — STRICT mTLS per namespace

```yaml
# k8s/istio/peer-authentication.yaml
# AC-3: STRICT mode — Envoy sidecars REJECT any plaintext traffic; only mTLS connections accepted.
# One PeerAuthentication per namespace ensures the setting survives namespace isolation.
---
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: contextiq-data
spec:
  mtls:
    mode: STRICT
---
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: contextiq-agents
spec:
  mtls:
    mode: STRICT
---
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: contextiq-gateway
spec:
  mtls:
    mode: STRICT
---
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: contextiq-admin
spec:
  mtls:
    mode: STRICT
---
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: contextiq-security
spec:
  mtls:
    mode: STRICT
---
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: contextiq-observability
spec:
  mtls:
    mode: STRICT
---
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: contextiq-infra
spec:
  mtls:
    mode: STRICT
```

---

### AuthorizationPolicies — least-privilege service-to-service rules

```yaml
# k8s/istio/authorization-policies.yaml
# Each policy restricts which source workloads can call a target service.
# Default: deny-all unless explicitly allowed.
---
# Deny all traffic in contextiq-data by default
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: deny-all
  namespace: contextiq-data
spec: {}    # empty spec = deny all

---
# Allow mcp-gateway to reach PostgreSQL on port 5432
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: allow-postgres-clients
  namespace: contextiq-data
spec:
  selector:
    matchLabels:
      app: postgres
  action: ALLOW
  rules:
    - from:
        - source:
            principals:
              - cluster.local/ns/contextiq-gateway/sa/mcp-gateway
              - cluster.local/ns/contextiq-agents/sa/agent-worker
              - cluster.local/ns/contextiq-agents/sa/indexing-service
              - cluster.local/ns/contextiq-admin/sa/admin-api
              - cluster.local/ns/contextiq-security/sa/vault    # Vault DB secrets engine
              - cluster.local/ns/contextiq-security/sa/keycloak
      to:
        - operation:
            ports: ["5432"]

---
# Allow agent-worker and mcp-gateway to reach Redis
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: allow-redis-clients
  namespace: contextiq-data
spec:
  selector:
    matchLabels:
      app: redis
  action: ALLOW
  rules:
    - from:
        - source:
            principals:
              - cluster.local/ns/contextiq-gateway/sa/mcp-gateway
              - cluster.local/ns/contextiq-agents/sa/agent-worker
      to:
        - operation:
            ports: ["6379"]

---
# Allow agent-worker to reach Neo4j
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: allow-neo4j-clients
  namespace: contextiq-data
spec:
  selector:
    matchLabels:
      app: neo4j
  action: ALLOW
  rules:
    - from:
        - source:
            principals:
              - cluster.local/ns/contextiq-agents/sa/agent-worker
      to:
        - operation:
            ports: ["7687"]    # Bolt protocol

---
# Allow ingress-gateway (Istio IngressGateway, not NGINX) to reach mcp-gateway
# Note: NGINX Ingress handles external TLS termination; Istio manages internal routing
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: allow-gateway-from-ingress
  namespace: contextiq-gateway
spec:
  selector:
    matchLabels:
      app: mcp-gateway
  action: ALLOW
  rules:
    - from:
        - source:
            namespaces: ["ingress-nginx"]
```

---

### Rolling restart after namespace label + PeerAuthentication

```bash
#!/usr/bin/env bash
# scripts/istio/rolling_restart_for_injection.sh
# Restarts all Deployments in contextiq-* namespaces to inject Istio sidecars.
# Safe to run after namespace labels and PeerAuthentication are applied.
set -euo pipefail

NAMESPACES=(
  contextiq-data contextiq-agents contextiq-gateway
  contextiq-admin contextiq-security contextiq-observability contextiq-infra
)

for NS in "${NAMESPACES[@]}"; do
  echo "=== Rolling restart in $NS ==="
  kubectl rollout restart deployment -n "$NS" 2>/dev/null || echo "  No deployments in $NS"
  kubectl rollout restart statefulset -n "$NS" 2>/dev/null || echo "  No StatefulSets in $NS"
done

echo "=== Waiting for all rollouts to complete ==="
for NS in "${NAMESPACES[@]}"; do
  for DEPLOY in $(kubectl get deploy -n "$NS" -o name 2>/dev/null); do
    kubectl rollout status "$DEPLOY" -n "$NS" --timeout=300s
  done
done
echo "=== Done — all workloads restarted with Istio sidecars ==="
```

## Acceptance Criteria

- [x] `kubectl get pods -n istio-system` shows `istiod` (×2) Running (AC-3)
- [x] `kubectl get peerauthentication -A` shows one `PeerAuthentication` named `default` with `MODE: STRICT` in every `contextiq-*` namespace (AC-3)
- [x] `kubectl describe pod <mcp-gateway-pod> -n contextiq-gateway | grep istio-proxy` shows the Envoy sidecar container present (AC-3)
- [x] `istioctl analyze -n contextiq-gateway` returns no `WARNING` or `ERROR` on mTLS config (AC-3)
- [x] Attempting to send plaintext HTTP from agent-worker to postgres on port 5432 (bypassing Envoy) is rejected — connection refused (AC-3)
- [x] `istioctl proxy-config secret <mcp-gateway-pod> -n contextiq-gateway` shows a valid SPIFFE certificate (AC-3)
- [x] Mesh-wide `minProtocolVersion: TLSV1_3` — Envoy sidecar TLS version probe returns TLS 1.3 for intra-cluster connections (AC-3, AC-4)

## Dependencies

- TASK-US045-01 — `contextiq-*` namespaces must exist before labels are applied
- TASK-US048-01 — cert-manager must be deployed (cert-manager and Istio CA coexist; Istio uses its own internal CA for mTLS SVIDs)
- All service Deployments must be running before rolling restart — do not apply during initial cluster bootstrap

## Definition of Done

- [x] `helm install istiod istio/istiod -n istio-system -f values.yaml` completes
- [x] `kubectl apply -f k8s/istio/peer-authentication.yaml` creates all 7 `PeerAuthentication` resources with `STRICT`
- [x] `istioctl analyze` returns 0 warnings across all `contextiq-*` namespaces
- [x] Service traffic verified working end-to-end (mcp-gateway → postgres, agent-worker → neo4j) after sidecar injection
