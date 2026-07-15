# TASK-US048-01 — cert-manager Deployment, Internal CA, Let's Encrypt, and Ingress TLS

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US048-01 |
| User Story | US-048 |
| Epic | EP-TECH-002 — Security Hardening & Secrets Management |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | Done |

## Description

Deploy cert-manager in the `contextiq-infra` namespace via Helm and configure two `ClusterIssuers`: (1) an internal CA issuer backed by a self-signed root certificate for internal service TLS, and (2) a Let's Encrypt ACME issuer for edge-facing Ingress resources (AC-1). Patch all existing `Ingress` objects to carry cert-manager TLS annotations so they receive certificates automatically (AC-2). cert-manager's built-in `renewBefore` mechanism handles automated renewal — certificates are renewed 30 days before expiry, satisfying the annual rotation requirement without manual intervention (AC-7).

## Implementation Details

**Technology:** cert-manager `v1.15.x` (`jetstack/cert-manager` Helm chart), Kubernetes 1.29+

**File locations:**
- `helm/charts/cert-manager/Chart.yaml`
- `helm/charts/cert-manager/values.yaml`
- `helm/charts/cert-manager/values-prod.yaml`
- `k8s/cert-manager/cluster-issuers.yaml` — `ClusterIssuer` resources
- `k8s/cert-manager/root-ca-secret.yaml` — self-signed root CA bootstrap
- `k8s/keycloak/ingress.yaml` — updated with cert-manager annotations
- `k8s/mcp-gateway/ingress.yaml` — updated
- `k8s/admin-portal/ingress.yaml` — updated
- `argocd/apps/services/cert-manager.yaml`

---

### cert-manager Helm wrapper

```yaml
# helm/charts/cert-manager/Chart.yaml
apiVersion: v2
name:        cert-manager
description: cert-manager deployment wrapper for ContextIQ
type:        application
version:     0.1.0
dependencies:
  - name:       cert-manager
    version:    "v1.15.3"
    repository: https://charts.jetstack.io
```

```yaml
# helm/charts/cert-manager/values.yaml
cert-manager:
  installCRDs: true    # install CRDs with the chart — avoids a separate kubectl apply step

  replicaCount: 2      # HA: two controller replicas

  resources:
    requests: { cpu: "100m", memory: "128Mi" }
    limits:   { cpu: "500m", memory: "512Mi" }

  # Prometheus metrics endpoint (scraped by existing ServiceMonitor in contextiq-observability)
  prometheus:
    enabled: true
    servicemonitor:
      enabled:   true
      namespace: contextiq-observability

  # Run in contextiq-infra namespace
  global:
    leaderElection:
      namespace: contextiq-infra

  webhook:
    replicaCount: 2
    resources:
      requests: { cpu: "50m",  memory: "64Mi" }
      limits:   { cpu: "200m", memory: "128Mi" }

  cainjector:
    replicaCount: 2
    resources:
      requests: { cpu: "50m",  memory: "64Mi" }
      limits:   { cpu: "200m", memory: "256Mi" }
```

---

### Bootstrap: self-signed root CA (run once before ClusterIssuers are applied)

```bash
#!/usr/bin/env bash
# scripts/cert-manager/bootstrap_root_ca.sh
# Creates the self-signed root CA certificate and stores it as a K8s Secret.
# This Secret is referenced by the 'internal-ca' ClusterIssuer.
# Run ONCE before deploying ClusterIssuers. Idempotent if Secret already exists.
set -euo pipefail

NAMESPACE="contextiq-infra"
SECRET_NAME="contextiq-root-ca"

if kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "Root CA Secret $NAMESPACE/$SECRET_NAME already exists — skipping."
  exit 0
fi

echo "=== Generating ContextIQ root CA ==="
# Generate root CA key (4096-bit RSA) and self-signed cert (10-year validity for the CA itself)
openssl genrsa -out /tmp/contextiq-ca.key 4096
openssl req -new -x509 -days 3650 \
  -key /tmp/contextiq-ca.key \
  -out /tmp/contextiq-ca.crt \
  -subj "/CN=ContextIQ Internal CA/O=ContextIQ/OU=Platform Engineering"

# Store in Kubernetes Secret
kubectl create secret tls "$SECRET_NAME" \
  --cert=/tmp/contextiq-ca.crt \
  --key=/tmp/contextiq-ca.key \
  --namespace="$NAMESPACE"

# Wipe temp files — private key must not persist on disk
rm -f /tmp/contextiq-ca.key /tmp/contextiq-ca.crt
echo "=== Root CA Secret created in $NAMESPACE/$SECRET_NAME ==="
```

---

### ClusterIssuers

```yaml
# k8s/cert-manager/cluster-issuers.yaml
---
# Issuer 1: Internal CA — used for all inter-service and database TLS (AC-1)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: contextiq-internal-ca
spec:
  ca:
    secretName: contextiq-root-ca    # created by bootstrap_root_ca.sh above
    # cert-manager reads tls.crt + tls.key from this Secret to sign certificate requests

---
# Issuer 2: Let's Encrypt — used for edge-facing Ingresses (AC-1)
# Uses DNS-01 challenge via Route53; swap solver for other DNS providers.
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    email:  platform-engineering@contextiq.io    # expiry alert notifications
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-prod-account-key    # ACME account private key (auto-generated)
    solvers:
      - dns01:
          route53:
            region: us-east-1
            # Credentials via IRSA (no static AWS keys)
            role: arn:aws:iam::ACCOUNT_ID:role/contextiq-cert-manager-dns01

---
# Staging Let's Encrypt issuer for non-prod environments
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    email:  platform-engineering@contextiq.io
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-staging-account-key
    solvers:
      - dns01:
          route53:
            region: us-east-1
            role: arn:aws:iam::ACCOUNT_ID:role/contextiq-cert-manager-dns01
```

---

### Ingress TLS annotations — pattern applied to all Ingress resources

```yaml
# k8s/keycloak/ingress.yaml  (representative — same pattern applied to mcp-gateway, admin-portal)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: keycloak
  namespace: contextiq-security
  annotations:
    # AC-2: cert-manager issues and renews the TLS certificate automatically
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # AC-7: cert-manager renews 30 days before expiry — satisfies annual rotation requirement
    cert-manager.io/renew-before:   "720h"    # 720h = 30 days
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - auth.contextiq.io
      secretName: keycloak-tls    # cert-manager writes the issued cert here automatically
  rules:
    - host: auth.contextiq.io
      http:
        paths:
          - path:     /
            pathType: Prefix
            backend:
              service:
                name: keycloak
                port: { number: 8080 }
```

```yaml
# k8s/mcp-gateway/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mcp-gateway
  namespace: contextiq-gateway
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    cert-manager.io/renew-before:   "720h"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - api.contextiq.io
      secretName: mcp-gateway-tls
  rules:
    - host: api.contextiq.io
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: mcp-gateway
                port: { number: 8000 }
```

```yaml
# k8s/admin-portal/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: admin-portal
  namespace: contextiq-admin
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    cert-manager.io/renew-before:   "720h"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - admin.contextiq.io
      secretName: admin-portal-tls
  rules:
    - host: admin.contextiq.io
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: admin-portal
                port: { number: 80 }
```

---

### ArgoCD Application

```yaml
# argocd/apps/services/cert-manager.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cert-manager
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://charts.jetstack.io
    chart:          cert-manager
    targetRevision: v1.15.3
    helm:
      valueFiles:
        - values.yaml
        - values-prod.yaml
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-infra
  syncPolicy:
    automated: { prune: true, selfHeal: true }
    syncOptions:
      - CreateNamespace=false    # namespace managed by TASK-US045-01
```

## Acceptance Criteria

- [x] `kubectl get pods -n contextiq-infra | grep cert-manager` shows controller (×2), webhook (×2), cainjector (×2) Running (AC-1)
- [x] `kubectl get clusterissuer` shows `contextiq-internal-ca` and `letsencrypt-prod` with `READY=True` (AC-1)
- [x] `kubectl get certificate -A` shows all Ingress TLS Secrets with `READY=True` and valid domains (AC-2)
- [x] `kubectl describe certificate keycloak-tls -n contextiq-security` shows `renewBefore: 720h0m0s` (AC-7)
- [x] `curl -I https://api.contextiq.io` returns `HTTP/2 200` with a valid TLS certificate in the chain (AC-2)
- [x] Cert expiry is >= 90 days from now (Let's Encrypt issues 90-day certs; renewBefore=30d ensures renewal at 60-day mark) (AC-7)

## Dependencies

- TASK-US045-01 — `contextiq-infra` namespace must exist
- TASK-US045-04 — ArgoCD App-of-Apps must include `cert-manager.yaml`
- AWS IAM role `contextiq-cert-manager-dns01` with Route53 permissions must exist for DNS-01 challenge
- NGINX Ingress Controller must be deployed and handling Ingress resources

## Definition of Done

- [x] `helm install cert-manager jetstack/cert-manager -n contextiq-infra -f values.yaml` completes with all pods Ready
- [x] `bootstrap_root_ca.sh` creates `contextiq-root-ca` Secret in `contextiq-infra`
- [x] All three Ingress resources (keycloak, mcp-gateway, admin-portal) have `READY=True` cert-manager Certificates
