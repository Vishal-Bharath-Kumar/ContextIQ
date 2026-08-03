#!/usr/bin/env bash
# scripts/vault/rotate_static_secrets.sh
# AC-5: Migrate remaining static Kubernetes Secrets to Vault KV v2 paths.
#
# Workflow:
#   1. Read each static secret value from its Kubernetes Secret object.
#   2. Write the value to the corresponding Vault KV v2 path.
#   3. Annotate the Kubernetes Secret with vault.hashicorp.com/migrated=true.
#   4. After all services are confirmed healthy using Vault-injected credentials,
#      the operator manually deletes the annotated Secret objects.
#
# Run ONCE during the initial Vault rollout. Idempotent — vault kv put is an upsert.
#
# Prerequisites:
#   VAULT_ADDR, VAULT_TOKEN   — set before running
#   kubectl                   — configured for the target cluster
set -euo pipefail

NAMESPACE_DATA="contextiq-data"
NAMESPACE_SECURITY="contextiq-security"

echo "=== Rotating static secrets to Vault KV v2 ==="

# ──────────────────────────────────────────────────────────────────────────────
# PostgreSQL admin credentials
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# Redis auth token
# ──────────────────────────────────────────────────────────────────────────────
REDIS_PASS=$(kubectl get secret redis-credentials -n "$NAMESPACE_DATA" \
  -o jsonpath='{.data.password}' | base64 -d)
vault kv put secret/contextiq/redis/admin \
  password="$REDIS_PASS"
kubectl annotate secret redis-credentials -n "$NAMESPACE_DATA" \
  vault.hashicorp.com/migrated="true" --overwrite
echo "  Redis credentials migrated."

# ──────────────────────────────────────────────────────────────────────────────
# Keycloak admin credentials
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# Entra ID OIDC client credentials
# ──────────────────────────────────────────────────────────────────────────────
ENTRA_CLIENT_ID=$(kubectl get secret entra-id-oidc-credentials -n "$NAMESPACE_SECURITY" \
  -o jsonpath='{.data.ENTRA_CLIENT_ID}' | base64 -d)
ENTRA_CLIENT_SECRET=$(kubectl get secret entra-id-oidc-credentials -n "$NAMESPACE_SECURITY" \
  -o jsonpath='{.data.ENTRA_CLIENT_SECRET}' | base64 -d)
ENTRA_TENANT_ID=$(kubectl get secret entra-id-oidc-credentials -n "$NAMESPACE_SECURITY" \
  -o jsonpath='{.data.ENTRA_TENANT_ID}' | base64 -d)
vault kv put secret/contextiq/entra_id \
  ENTRA_CLIENT_ID="$ENTRA_CLIENT_ID" \
  ENTRA_CLIENT_SECRET="$ENTRA_CLIENT_SECRET" \
  ENTRA_TENANT_ID="$ENTRA_TENANT_ID"
kubectl annotate secret entra-id-oidc-credentials -n "$NAMESPACE_SECURITY" \
  vault.hashicorp.com/migrated="true" --overwrite
echo "  Entra ID credentials migrated."

# ──────────────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "=== Static secret rotation complete ==="
echo ""
echo "Migrated Secrets are annotated vault.hashicorp.com/migrated=true."
echo "Next steps:"
echo "  1. Verify all services start correctly and use Vault-injected credentials."
echo "  2. List migrated Secrets:"
echo "       kubectl get secret -A -l vault.hashicorp.com/migrated=true"
echo "  3. After confirming service stability, delete each annotated Secret:"
echo "       kubectl delete secret postgres-admin-credentials -n $NAMESPACE_DATA"
echo "       kubectl delete secret redis-credentials           -n $NAMESPACE_DATA"
echo "       kubectl delete secret keycloak-admin-credentials  -n $NAMESPACE_SECURITY"
echo "       kubectl delete secret entra-id-oidc-credentials   -n $NAMESPACE_SECURITY"
