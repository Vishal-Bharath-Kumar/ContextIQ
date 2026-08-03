# TASK-US001-02 — Deploy MCP Gateway to Kubernetes with Ingress

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US001-02 |
| User Story | US-001 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | In Progress |

## Description

Create the Kubernetes Helm chart resources for the `contextiq-gateway` service: Deployment, Service, Ingress, ConfigMap, and NetworkPolicy. The gateway must be reachable from AI assistants external to the cluster and isolated from unapproved internal traffic.

## Implementation Details

**Technology:** Kubernetes 1.28+, Helm 3, NGINX Ingress Controller, cert-manager

**File locations:**
- `helm/contextiq-gateway/templates/deployment.yaml`
- `helm/contextiq-gateway/templates/service.yaml`
- `helm/contextiq-gateway/templates/ingress.yaml`
- `helm/contextiq-gateway/templates/networkpolicy.yaml`
- `helm/contextiq-gateway/values.yaml`

**Key implementation steps:**

1. **Deployment** — `contextiq-gateway` in namespace `contextiq-gateway`:
   - `replicas: 2` (minimum for HA; HPA configured in US-046)
   - Container port `8080`; resource requests `cpu: 250m, memory: 256Mi`; limits `cpu: 1000m, memory: 512Mi`
   - Readiness probe: `GET /healthz` every 10 s, failure threshold 3
   - Liveness probe: `GET /healthz` every 30 s, failure threshold 5
   - Environment variables from `ConfigMap` + secrets from Vault via sidecar injector

2. **Service** — `ClusterIP` type, port `80 → 8080`

3. **Ingress** — NGINX class:
   ```yaml
   annotations:
     nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"  # SSE long-poll
     nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
   ```
   TLS termination via cert-manager `Certificate` resource (Let's Encrypt / internal CA)

4. **NetworkPolicy** — default-deny; allow:
   - Ingress from `ingress-nginx` namespace on port 8080
   - Egress to `contextiq-agents` namespace on port 8000
   - Egress to `contextiq-security` namespace on port 8200 (Vault)
   - Egress to `kube-dns` on port 53

5. **PodDisruptionBudget** — `minAvailable: 1`

## Acceptance Criteria

- [x] `helm lint` passes with no errors on the chart
- [ ] `helm install --dry-run` succeeds in the target cluster
- [ ] Deployment rolls out: `kubectl rollout status deployment/contextiq-gateway -n contextiq-gateway` succeeds
- [ ] `GET https://<ingress-host>/mcp/sse` is reachable from outside the cluster
- [ ] Direct pod-to-pod traffic from `contextiq-data` namespace is blocked by NetworkPolicy (verified with `netcat` test pod)
- [ ] TLS certificate is issued and valid (cert-manager `Certificate` status = `Ready`)

## Dependencies

- TASK-US001-01 (Docker image built and pushed)
- US-045 (K8s cluster and namespace scaffold)
- EP-TECH-002 (cert-manager TLS — US-048)

## Definition of Done

- [x] Helm chart merged to `infra/` in main repository
- [x] ArgoCD Application resource created for `contextiq-gateway`
- [ ] Deployment verified in staging environment
- [ ] NetworkPolicy ingress/egress validated via `kubectl auth can-i` and network test pods
