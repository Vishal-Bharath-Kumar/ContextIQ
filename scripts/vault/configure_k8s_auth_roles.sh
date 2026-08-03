#!/usr/bin/env bash
# scripts/vault/configure_k8s_auth_roles.sh
# Bind Kubernetes ServiceAccounts to Vault policies via the Kubernetes auth method.
# Each role ties a specific namespace+ServiceAccount pair to one Vault policy.
# Idempotent — vault write auth/kubernetes/role/<name> is an upsert.
#
# Prerequisites:
#   VAULT_ADDR, VAULT_TOKEN set before running.
#   Kubernetes auth method must already be enabled and configured
#   (see scripts/vault/init_vault.sh).
set -euo pipefail

echo "=== Configuring Kubernetes auth roles ==="

# Format: VAULT_ROLE="namespace:service_account_name:vault_policy"
declare -A ROLES=(
  ["mcp-gateway"]="contextiq-gateway:mcp-gateway:mcp-gateway"
  ["agent-worker"]="contextiq-agents:agent-worker:agent-worker"
  ["indexing-service"]="contextiq-agents:indexing-service:indexing-service"
  ["admin-api"]="contextiq-admin:admin-api:admin-api"
  ["keycloak"]="contextiq-security:keycloak:keycloak"
)

for VAULT_ROLE in "${!ROLES[@]}"; do
  IFS=":" read -r NAMESPACE SA_NAME POLICY <<< "${ROLES[$VAULT_ROLE]}"
  vault write "auth/kubernetes/role/$VAULT_ROLE" \
    bound_service_account_names      = "$SA_NAME" \
    bound_service_account_namespaces = "$NAMESPACE" \
    policies                         = "$POLICY" \
    ttl                              = "1h"   # AC-4: Vault Agent token TTL
  echo "  Role $VAULT_ROLE → namespace=$NAMESPACE sa=$SA_NAME policy=$POLICY"
done

echo "=== Kubernetes auth roles configured ==="
