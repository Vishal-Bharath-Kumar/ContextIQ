#!/usr/bin/env bash
# scripts/vault/configure_policies.sh
# Write per-service Vault policies following the principle of least privilege.
# Each policy grants only the paths the service genuinely needs (OWASP A01).
# Idempotent — vault policy write is an upsert.
#
# Prerequisites: VAULT_ADDR, VAULT_TOKEN set before running.
set -euo pipefail

echo "=== Writing Vault policies ==="

# ──────────────────────────────────────────────────────────────────────────────
# mcp-gateway: PostgreSQL + Redis dynamic credentials + static KV for Keycloak
# ──────────────────────────────────────────────────────────────────────────────
vault policy write mcp-gateway - <<'EOF'
# PostgreSQL dynamic credentials
path "database/postgres/creds/mcp-gateway" {
  capabilities = ["read"]
}
# Redis dynamic credentials
path "database/redis/creds/mcp-gateway" {
  capabilities = ["read"]
}
# Keycloak / OPA connection config (static KV)
path "secret/data/contextiq/keycloak/*" {
  capabilities = ["read"]
}
# Connector vault_path secrets (read only)
path "secret/data/contextiq/connectors/*" {
  capabilities = ["read"]
}
EOF

# ──────────────────────────────────────────────────────────────────────────────
# agent-worker: all four data stores
# ──────────────────────────────────────────────────────────────────────────────
vault policy write agent-worker - <<'EOF'
path "database/postgres/creds/agent-worker" { capabilities = ["read"] }
path "database/redis/creds/agent-worker"    { capabilities = ["read"] }
path "database/neo4j/creds/agent-worker"    { capabilities = ["read"] }
path "secret/data/contextiq/qdrant/api-key" { capabilities = ["read"] }
EOF

# ──────────────────────────────────────────────────────────────────────────────
# indexing-service: PostgreSQL + Qdrant only
# ──────────────────────────────────────────────────────────────────────────────
vault policy write indexing-service - <<'EOF'
path "database/postgres/creds/indexing-service" { capabilities = ["read"] }
path "secret/data/contextiq/qdrant/api-key"     { capabilities = ["read"] }
EOF

# ──────────────────────────────────────────────────────────────────────────────
# admin-api: PostgreSQL + Redis + identity provider configs
# ──────────────────────────────────────────────────────────────────────────────
vault policy write admin-api - <<'EOF'
path "database/postgres/creds/admin-api"    { capabilities = ["read"] }
path "database/redis/creds/mcp-gateway"     { capabilities = ["read"] }
path "secret/data/contextiq/keycloak/*"     { capabilities = ["read"] }
path "secret/data/contextiq/entra_id"       { capabilities = ["read"] }
path "secret/data/contextiq/saml_idp"       { capabilities = ["read"] }
EOF

# ──────────────────────────────────────────────────────────────────────────────
# keycloak: PostgreSQL only
# ──────────────────────────────────────────────────────────────────────────────
vault policy write keycloak - <<'EOF'
path "database/postgres/creds/keycloak"     { capabilities = ["read"] }
path "secret/data/contextiq/keycloak/*"     { capabilities = ["read"] }
EOF

echo "=== Vault policies written ==="
echo "Policies created: mcp-gateway, agent-worker, indexing-service, admin-api, keycloak"
