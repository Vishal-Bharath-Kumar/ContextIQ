#!/usr/bin/env bash
# scripts/vault/configure_postgres_secrets.sh
# Enable and configure the Vault database secrets engine for PostgreSQL.
# Idempotent — safe to re-run.
#
# Prerequisites:
#   VAULT_ADDR, VAULT_TOKEN   — set before running
#   POSTGRES_ADMIN_USER       — PostgreSQL superuser name
#   POSTGRES_ADMIN_PASSWORD   — PostgreSQL superuser password
set -euo pipefail

MOUNT="database/postgres"

echo "=== Enabling PostgreSQL secrets engine at $MOUNT ==="
vault secrets enable -path="$MOUNT" database 2>/dev/null || echo "  Already enabled."

echo "=== Configuring PostgreSQL connection ==="
# Vault connects as the admin user to CREATE ROLE on demand.
# Admin credentials are passed via environment — never hard-coded.
vault write "$MOUNT/config/contextiq" \
  plugin_name             = "postgresql-database-plugin" \
  allowed_roles           = "mcp-gateway,agent-worker,indexing-service,admin-api,keycloak" \
  connection_url          = "postgresql://{{username}}:{{password}}@postgres.contextiq-data.svc.cluster.local:5432/contextiq?sslmode=require" \
  username                = "${POSTGRES_ADMIN_USER}" \
  password                = "${POSTGRES_ADMIN_PASSWORD}" \
  password_authentication = "scram-sha-256"

echo "=== Configuring dynamic roles (TTL: 1h / max 2h) ==="
# AC-4: 1h TTL, 2h max TTL; short-lived credentials renewed by Vault Agent sidecar
for ROLE in mcp-gateway agent-worker indexing-service admin-api keycloak; do
  vault write "$MOUNT/roles/$ROLE" \
    db_name               = "contextiq" \
    creation_statements   = "CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT CONNECT ON DATABASE contextiq TO \"{{name}}\"; GRANT USAGE ON SCHEMA public TO \"{{name}}\"; GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
    revocation_statements = "DROP ROLE IF EXISTS \"{{name}}\";" \
    default_ttl           = "1h" \
    max_ttl               = "2h"
  echo "  Role $ROLE configured."
done

echo "=== PostgreSQL secrets engine ready ==="
