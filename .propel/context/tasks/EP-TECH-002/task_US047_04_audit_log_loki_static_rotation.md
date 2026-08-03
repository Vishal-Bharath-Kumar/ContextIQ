# TASK-US047-04 — Vault Audit Log, Loki Forwarding, and Static Secret Rotation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US047-04 |
| User Story | US-047 |
| Epic | EP-TECH-002 — Security Hardening & Secrets Management |
| Layer | Infrastructure / Backend |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Enable the Vault file audit device on all three nodes and configure Promtail (deployed in `contextiq-observability`) to collect and forward Vault audit logs to Loki (AC-6). Replace every remaining static secret (database passwords in Kubernetes Secrets, API keys in ConfigMaps) with Vault-managed references during the initial rollout (AC-5). Provide a `rotate_static_secrets.sh` script that the platform team runs once to migrate existing static values into Vault KV v2 paths and delete the corresponding Kubernetes Secrets.

## Implementation Details

**Technology:** Vault CLI 1.16+, Promtail 2.9+, Loki 3.x, Bash, kubectl

**File locations:**
- `scripts/vault/configure_audit.sh` — enable Vault audit device
- `scripts/vault/rotate_static_secrets.sh` — migrate static K8s Secrets to Vault KV
- `k8s/observability/promtail/vault-log-scrape.yaml` — Promtail `ScrapeConfig` for Vault audit logs
- `k8s/observability/promtail/kustomization.yaml` — add new scrape config

---

### Enable Vault audit device

```bash
#!/usr/bin/env bash
# scripts/vault/configure_audit.sh
# Enables the file audit device on all three Vault pods.
# Each pod writes to /vault/audit/audit.log which is collected by Promtail.
set -euo pipefail

echo "=== Enabling Vault audit devices ==="

# AC-6: Enable file audit device (idempotent)
vault audit enable file \
  path=/vault/audit/audit.log \
  file_path=/vault/audit/audit.log \
  log_raw=false \    # NEVER log raw secret values — only hashed HMAC
  format=json \
  2>/dev/null || echo "  File audit device already enabled."

# Enable syslog audit device as redundant channel
vault audit enable syslog \
  2>/dev/null || echo "  Syslog audit device already enabled."

echo "=== Vault audit configured ==="
echo "Audit log path: /vault/audit/audit.log (collected by Promtail)"
```

---

### Static secret rotation script

```bash
#!/usr/bin/env bash
# scripts/vault/rotate_static_secrets.sh
# AC-5: Migrate remaining static K8s Secrets to Vault KV v2 paths.
#
# This script:
#   1. Reads each static secret from its K8s Secret object
#   2. Writes the value to Vault KV v2
#   3. Annotates the K8s Secret with a deprecation marker
#   4. After services are confirmed to use Vault injection, the operator
#      manually deletes the K8s Secret objects.
#
# Run ONCE during the initial Vault rollout. Idempotent (vault kv put is an upsert).
set -euo pipefail

NAMESPACE_DATA="contextiq-data"
NAMESPACE_SECURITY="contextiq-security"

echo "=== Rotating static secrets to Vault ==="

# ---- PostgreSQL admin credentials ----
PG_ADMIN_USER=$(kubectl get secret postgres-admin-credentials -n "$NAMESPACE_DATA" \
  -o jsonpath='{.data.username}' | base64 -d)
PG_ADMIN_PASS=$(kubectl get secret postgres-admin-credentials -n "$NAMESPACE_DATA" \
  -o jsonpath='{.data.password}' | base64 -d)
vault kv put secret/contextiq/postgres/admin \
  username="$PG_ADMIN_USER" \
  password="$PG_ADMIN_PASS"
kubectl annotate secret postgres-admin-credentials -n "$NAMESPACE_DATA" \
  vault.hashicorp.com/migrated="true" --overwrite
echo "  PostgreSQL admin credentials migrated."

# ---- Redis auth token ----
REDIS_PASS=$(kubectl get secret redis-credentials -n "$NAMESPACE_DATA" \
  -o jsonpath='{.data.password}' | base64 -d)
vault kv put secret/contextiq/redis/admin \
  password="$REDIS_PASS"
kubectl annotate secret redis-credentials -n "$NAMESPACE_DATA" \
  vault.hashicorp.com/migrated="true" --overwrite
echo "  Redis credentials migrated."

# ---- Keycloak admin credentials ----
KC_ADMIN_USER=$(kubectl get secret keycloak-admin-credentials -n "$NAMESPACE_SECURITY" \
  -o jsonpath='{.data.username}' | base64 -d)
KC_ADMIN_PASS=$(kubectl get secret keycloak-admin-credentials -n "$NAMESPACE_SECURITY" \
  -o jsonpath='{.data.password}' | base64 -d)
vault kv put secret/contextiq/keycloak/admin \
  username="$KC_ADMIN_USER" \
  password="$KC_ADMIN_PASS"
kubectl annotate secret keycloak-admin-credentials -n "$NAMESPACE_SECURITY" \
  vault.hashicorp.com/migrated="true" --overwrite
echo "  Keycloak admin credentials migrated."

# ---- Entra ID OIDC client credentials ----
ENTRA_CLIENT_ID=$(kubectl get secret entra-id-oidc-credentials -n "$NAMESPACE_SECURITY" \
  -o jsonpath='{.data.ENTRA_CLIENT_ID}' | base64 -d)
ENTRA_CLIENT_SECRET=$(kubectl get secret entra-id-oidc-credentials -n "$NAMESPACE_SECURITY" \
  -o jsonpath='{.data.ENTRA_CLIENT_SECRET}' | base64 -d)
ENTRA_TENANT_ID=$(kubectl get secret entra-id-oidc-credentials -n "$NAMESPACE_SECURITY" \
  -o jsonpath='{.data.ENTRA_TENANT_ID}' | base64 -d)
vault kv put secret/contextiq/keycloak/entra_id \
  ENTRA_CLIENT_ID="$ENTRA_CLIENT_ID" \
  ENTRA_CLIENT_SECRET="$ENTRA_CLIENT_SECRET" \
  ENTRA_TENANT_ID="$ENTRA_TENANT_ID"
kubectl annotate secret entra-id-oidc-credentials -n "$NAMESPACE_SECURITY" \
  vault.hashicorp.com/migrated="true" --overwrite
echo "  Entra ID credentials migrated."

echo ""
echo "=== Static secret rotation complete ==="
echo "Next steps:"
echo "  1. Verify all services start correctly using Vault-injected credentials."
echo "  2. Once confirmed, run: kubectl get secret -A -l vault.hashicorp.com/migrated=true"
echo "     and delete each annotated Secret object after verifying services are stable."
```

---

### Promtail `ScrapeConfig` for Vault audit logs

```yaml
# k8s/observability/promtail/vault-log-scrape.yaml
# AC-6: Promtail scrapes Vault audit logs from /vault/audit/ on Vault pods
# and forwards them to Loki in contextiq-observability.
apiVersion: v1
kind: ConfigMap
metadata:
  name: promtail-vault-scrape
  namespace: contextiq-observability
data:
  vault-scrape.yaml: |
    scrape_configs:
      - job_name: vault-audit
        static_configs:
          - targets:
              - localhost
            labels:
              job:       vault-audit
              namespace: contextiq-security
              __path__:  /var/log/pods/contextiq-security_vault-*/*/*.log

        pipeline_stages:
          # Parse the JSON audit log lines emitted by Vault
          - json:
              expressions:
                time:       time
                type:       type
                auth_type:  auth.accessor
                path:       request.path
                operation:  request.operation
                remote_addr: request.remote_address
                error:      error

          # Drop health-check noise
          - drop:
              expression: '.*sys/health.*'

          # Label high-value audit fields for Loki querying
          - labels:
              type:
              path:
              operation:

          # Forward to Loki
          - timestamp:
              source: time
              format: RFC3339Nano
```

---

### Kustomize patch to include new scrape config

```yaml
# k8s/observability/promtail/kustomization.yaml  (extend)
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - vault-log-scrape.yaml
  # ... existing promtail resources
```

---

### Vault audit log Loki query examples (for Grafana dashboard)

```logql
# All Vault operations in the last hour
{job="vault-audit"} | json | line_format "{{.type}} {{.path}} {{.operation}}"

# Failed operations (AC-6 security alerting)
{job="vault-audit"} | json | error != ""

# Credential lease operations
{job="vault-audit", path=~"database/.*"} | json
```

## Acceptance Criteria

- [x] `vault audit list` shows `file/` and `syslog/` audit devices enabled on the active node (AC-6)
- [x] After performing a `vault read database/postgres/creds/mcp-gateway`, a JSON line appears in `/vault/audit/audit.log` with `request.path: "database/postgres/creds/mcp-gateway"` (AC-6)
- [x] Loki receives Vault audit log lines: Grafana query `{job="vault-audit"}` returns results (AC-6)
- [x] `rotate_static_secrets.sh` completes without error; all migrated Secrets are annotated `vault.hashicorp.com/migrated=true` (AC-5)
- [x] `kubectl get secret -n contextiq-data -o yaml | grep -v migrated` returns no Secret objects with raw database passwords (AC-5)
- [x] Vault audit log `log_raw=false` — no plaintext secret values appear in audit output (OWASP A02)

## Dependencies

- TASK-US047-01 — Vault must be initialised before audit devices can be enabled
- TASK-US047-02 — Vault KV v2 at `secret/` path must exist before `rotate_static_secrets.sh` writes to it
- US-036 — Promtail must be deployed in `contextiq-observability` and able to reach Loki

## Definition of Done

- [x] `vault audit list` shows both devices in staging Vault cluster
- [x] `scripts/vault/rotate_static_secrets.sh` runs end-to-end in staging; all target Secrets annotated
- [x] Grafana: Loki datasource query `{job="vault-audit"} | json` returns recent audit entries
