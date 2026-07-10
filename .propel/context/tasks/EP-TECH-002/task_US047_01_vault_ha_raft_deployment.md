# TASK-US047-01 — Vault HA Raft Deployment with Cloud KMS Auto-Unseal

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US047-01 |
| User Story | US-047 |
| Epic | EP-TECH-002 — Security Hardening & Secrets Management |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Deploy HashiCorp Vault in HA Raft mode with 3 nodes in the `contextiq-security` namespace (AC-1). Configure auto-unseal via cloud KMS so that Vault pods unseal automatically on restart without operator intervention. Install the Vault Agent Injector (bundled with the Vault Helm chart) which enables per-pod sidecar injection of dynamic credentials in subsequent tasks. Apply `PodDisruptionBudget` (minAvailable 2) and `podAntiAffinity` to spread Vault nodes across distinct cluster nodes.

## Implementation Details

**Technology:** `hashicorp/vault` Helm chart `0.28.x`, Kubernetes 1.29+, AWS KMS (primary) or GCP Cloud KMS (alternate)

**File locations:**
- `helm/charts/vault/Chart.yaml` — thin wrapper chart
- `helm/charts/vault/values.yaml` — Raft HA + KMS auto-unseal defaults
- `helm/charts/vault/values-prod.yaml`
- `helm/charts/vault/config/vault-config.hcl.tpl` — Vault HCL config template (embedded in values)
- `argocd/apps/services/vault.yaml`
- `scripts/vault/init_vault.sh` — one-time init + root token bootstrap

---

### Vault Helm values

```yaml
# helm/charts/vault/values.yaml
global:
  enabled: true
  tlsDisable: false    # TLS enabled between Vault nodes and clients (US-048)

injector:
  enabled:  true       # Vault Agent Injector — required for AC-3 sidecar injection
  replicas: 2          # HA: two injector pods so pod creation works during injector rolling upgrade
  resources:
    requests: { cpu: "250m", memory: "256Mi" }
    limits:   { cpu: "500m", memory: "512Mi" }

server:
  image:
    repository: hashicorp/vault
    tag:        "1.16.2"    # pin to a specific release for reproducibility

  # HA Raft configuration — 3 nodes (AC-1)
  ha:
    enabled:   true
    replicas:  3
    raft:
      enabled: true
      setNodeId: true
      config: |
        ui = true

        listener "tcp" {
          tls_disable     = 0
          address         = "[::]:8200"
          cluster_address = "[::]:8201"
          tls_cert_file   = "/vault/userconfig/vault-tls/tls.crt"
          tls_key_file    = "/vault/userconfig/vault-tls/tls.key"
          tls_client_ca_file = "/vault/userconfig/vault-tls/ca.crt"
        }

        storage "raft" {
          path    = "/vault/data"
          node_id = "VAULT_NODE_ID"    # replaced at pod start by setNodeId: true

          retry_join {
            leader_api_addr = "https://vault-0.vault-internal:8200"
            leader_ca_cert_file = "/vault/userconfig/vault-tls/ca.crt"
          }
          retry_join {
            leader_api_addr = "https://vault-1.vault-internal:8200"
            leader_ca_cert_file = "/vault/userconfig/vault-tls/ca.crt"
          }
          retry_join {
            leader_api_addr = "https://vault-2.vault-internal:8200"
            leader_ca_cert_file = "/vault/userconfig/vault-tls/ca.crt"
          }
        }

        # AC-1: auto-unseal via AWS KMS — prevents manual unseal on pod restart
        seal "awskms" {
          region     = "us-east-1"
          kms_key_id = "alias/contextiq-vault-unseal"
          # Credentials provided via Pod IAM role (IRSA) — not hard-coded
        }

        service_registration "kubernetes" {}

  # Persistent storage for Raft data
  dataStorage:
    enabled:      true
    size:         "10Gi"
    storageClass: "gp3"    # AWS gp3; replace with your cloud's high-IOPS class

  # Anti-affinity: spread Vault pods across distinct nodes (AC-1 HA)
  affinity: |
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchLabels:
              app.kubernetes.io/name: vault
              component: server
          topologyKey: kubernetes.io/hostname

  # Resource bounds
  resources:
    requests: { cpu: "500m",  memory: "1Gi" }
    limits:   { cpu: "2",     memory: "4Gi" }

  # Security context — run as non-root
  securityContext:
    runAsNonRoot:             true
    runAsUser:                100    # vault user in the official image
    allowPrivilegeEscalation: false
    capabilities:
      drop: ["ALL"]
      add:  ["IPC_LOCK"]    # required by Vault to prevent memory from being swapped

  # Readiness: Vault is ready only when unsealed and active/standby
  readinessProbe:
    exec:
      command: ["/bin/sh", "-ec", "vault status -tls-skip-verify"]
    initialDelaySeconds: 5
    periodSeconds:       5
    failureThreshold:    2

  # PodDisruptionBudget — at least 2 nodes available during voluntary disruptions
  podDisruptionBudget:
    enabled:      true
    minAvailable: 2

ui:
  enabled:      true
  serviceType:  ClusterIP    # exposed via Ingress at /vault path

# Vault namespace
server:
  serviceAccount:
    create: true
    name:   vault
    annotations:
      # AWS IRSA — grants the Vault pod permission to call KMS without static credentials
      eks.amazonaws.com/role-arn: "arn:aws:iam::ACCOUNT_ID:role/contextiq-vault-unseal"
```

---

### GCP Cloud KMS override (alternative to AWS KMS)

```yaml
# helm/charts/vault/values-gcp.yaml
# Override the seal stanza for GCP environments
server:
  ha:
    raft:
      config: |
        seal "gcpckms" {
          project    = "your-gcp-project"
          region     = "global"
          key_ring   = "contextiq-vault"
          crypto_key = "vault-unseal"
          # Credentials provided via Workload Identity — not hard-coded
        }
```

---

### Vault init script (one-time bootstrap — run once after first deployment)

```bash
#!/usr/bin/env bash
# scripts/vault/init_vault.sh
# One-time Vault initialization and Kubernetes auth configuration.
#
# Prerequisites:
#   - Vault pods are Running (but sealed/uninitialized)
#   - kubectl access to contextiq-security namespace
#   - vault CLI installed locally
#
# SECURITY: The root token and unseal keys are printed to stdout and must be
# saved to a secure offline location immediately. They are NOT stored anywhere
# by this script.
set -euo pipefail

NAMESPACE="contextiq-security"
VAULT_POD="vault-0"

echo "=== Port-forwarding to vault-0 ==="
kubectl port-forward -n "$NAMESPACE" "$VAULT_POD" 8200:8200 &
PF_PID=$!
sleep 3
trap "kill $PF_PID 2>/dev/null" EXIT

export VAULT_ADDR="https://127.0.0.1:8200"
export VAULT_SKIP_VERIFY="true"    # skip TLS verify for local port-forward

echo "=== Initialising Vault (5 key shares, 3 threshold) ==="
vault operator init \
  -key-shares=5 \
  -key-threshold=3 \
  -format=json | tee /tmp/vault-init.json

echo ""
echo "IMPORTANT: Save /tmp/vault-init.json to an offline secure location NOW."
echo "This file contains the root token and unseal keys. Delete it after saving."
echo ""

# Extract root token for subsequent setup steps
ROOT_TOKEN=$(jq -r '.root_token' /tmp/vault-init.json)
export VAULT_TOKEN="$ROOT_TOKEN"

echo "=== Enabling Kubernetes auth method ==="
vault auth enable kubernetes

echo "=== Configuring Kubernetes auth ==="
# Vault reads the K8s API server CA and service account JWT from the pod's projected volume
vault write auth/kubernetes/config \
  kubernetes_host="https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT}" \
  token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" \
  kubernetes_ca_cert="@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt" \
  issuer="https://kubernetes.default.svc.cluster.local"

echo "=== Vault initialisation complete ==="
echo "Root token stored in VAULT_TOKEN env var for subsequent setup scripts."
```

---

### ArgoCD Application

```yaml
# argocd/apps/services/vault.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: vault
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://helm.releases.hashicorp.com
    chart:          vault
    targetRevision: "0.28.1"
    helm:
      valueFiles:
        - values.yaml
        - values-prod.yaml
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-security
  syncPolicy:
    automated: { prune: false, selfHeal: true }
    # prune: false — Vault StatefulSet and PVCs must not be deleted automatically
```

## Acceptance Criteria

- [ ] `kubectl get pods -n contextiq-security | grep vault` shows 3 Running vault-server pods + 2 injector pods (AC-1)
- [ ] `vault status` shows `HA Mode: active` on one pod and `standby` on others (AC-1)
- [ ] `vault status -format=json | jq .sealed` returns `false` after pod restart — KMS auto-unseal working (AC-1)
- [ ] `kubectl get pdb -n contextiq-security` shows `ALLOWED-DISRUPTIONS: 1` (AC-1 HA)
- [ ] Vault Agent Injector webhook is registered: `kubectl get mutatingwebhookconfiguration | grep vault` (needed for AC-3)

## Dependencies

- TASK-US045-01 — `contextiq-security` namespace must exist
- TASK-US045-04 — ArgoCD App-of-Apps must include `vault.yaml`
- AWS IAM role `contextiq-vault-unseal` with `kms:Decrypt`, `kms:Encrypt`, `kms:DescribeKey` must be pre-created
- KMS key `alias/contextiq-vault-unseal` must exist before first deployment

## Definition of Done

- [ ] `helm install vault hashicorp/vault -n contextiq-security -f values.yaml -f values-prod.yaml` completes
- [ ] All 3 Vault pods pass readiness probe (`vault status` exits 0)
- [ ] `init_vault.sh` runs successfully on first deployment; operator saves generated keys offline
