# TASK-US047-02 — Database Secrets Engines: PostgreSQL, Redis, Neo4j, and Qdrant

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US047-02 |
| User Story | US-047 |
| Epic | EP-TECH-002 — Security Hardening & Secrets Management |
| Layer | Infrastructure / Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Enable and configure the Vault database secrets engine for each of the four data stores (AC-2). Each secrets engine mount registers a connection configuration (Vault connects to the database as an admin user) and creates one or more dynamic roles that Vault uses to generate short-lived, unique credentials on demand. All dynamic credentials are issued with a 1-hour TTL and a maximum lease duration of 2 hours, automatically renewed by the Vault Agent sidecar before expiry (AC-4). Configuration is expressed as idempotent Bash scripts so they can be re-run safely in CI.

## Implementation Details

**Technology:** Vault CLI 1.16+, Python 3.11+

**File locations:**
- `scripts/vault/configure_postgres_secrets.sh` — PostgreSQL engine + roles
- `scripts/vault/configure_redis_secrets.sh` — Redis engine + roles
- `scripts/vault/configure_neo4j_secrets.sh` — Neo4j engine (database plugin)
- `scripts/vault/configure_qdrant_secrets.sh` — Qdrant static-secret wrapper (Qdrant lacks a native Vault plugin; credentials are rotated via static secret with short TTL)
- `scripts/vault/configure_policies.sh` — per-service Vault policies
- `scripts/vault/configure_k8s_auth_roles.sh` — Kubernetes auth roles per service account

---

### PostgreSQL secrets engine

```bash
#!/usr/bin/env bash
# scripts/vault/configure_postgres_secrets.sh
# Idempotent — safe to re-run.
set -euo pipefail

# Prerequisites: VAULT_ADDR, VAULT_TOKEN set; Vault reachable
MOUNT="database/postgres"

echo "=== Enabling PostgreSQL secrets engine at $MOUNT ==="
vault secrets enable -path="$MOUNT" database 2>/dev/null || echo "  Already enabled."

echo "=== Configuring PostgreSQL connection ==="
# Vault connects as the admin user to CREATE ROLE on demand.
# Admin credentials are stored in Vault itself (bootstrapped once by the operator).
vault write "$MOUNT/config/contextiq" \
  plugin_name        = "postgresql-database-plugin" \
  allowed_roles      = "mcp-gateway,agent-worker,indexing-service,admin-api,keycloak" \
  connection_url     = "postgresql://{{username}}:{{password}}@postgres.contextiq-data.svc.cluster.local:5432/contextiq?sslmode=require" \
  username           = "${POSTGRES_ADMIN_USER}" \
  password           = "${POSTGRES_ADMIN_PASSWORD}" \
  password_authentication = "scram-sha-256"

# AC-4: 1h TTL, 2h max TTL per dynamic role
for ROLE in mcp-gateway agent-worker indexing-service admin-api keycloak; do
  vault write "$MOUNT/roles/$ROLE" \
    db_name             = "contextiq" \
    creation_statements = "CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT CONNECT ON DATABASE contextiq TO \"{{name}}\"; GRANT USAGE ON SCHEMA public TO \"{{name}}\"; GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
    revocation_statements = "DROP ROLE IF EXISTS \"{{name}}\";" \
    default_ttl         = "1h" \
    max_ttl             = "2h"
  echo "  Role $ROLE configured."
done

echo "=== PostgreSQL secrets engine ready ==="
```

---

### Redis secrets engine

```bash
#!/usr/bin/env bash
# scripts/vault/configure_redis_secrets.sh
# Vault's Redis database plugin issues ACL-based credentials.
set -euo pipefail

MOUNT="database/redis"

echo "=== Enabling Redis secrets engine at $MOUNT ==="
vault secrets enable -path="$MOUNT" database 2>/dev/null || echo "  Already enabled."

vault write "$MOUNT/config/contextiq-redis" \
  plugin_name  = "redis-database-plugin" \
  allowed_roles = "mcp-gateway,agent-worker" \
  host          = "redis.contextiq-data.svc.cluster.local" \
  port          = 6379 \
  username      = "${REDIS_ADMIN_USER}" \
  password      = "${REDIS_ADMIN_PASSWORD}" \
  tls           = true

for ROLE in mcp-gateway agent-worker; do
  vault write "$MOUNT/roles/$ROLE" \
    db_name    = "contextiq-redis" \
    creation_statements = "{\"rules\":[{\"rule_type\":\"commandkeypattern\",\"rule\":\"allcommands~*\"}]}" \
    default_ttl = "1h" \
    max_ttl     = "2h"
  echo "  Redis role $ROLE configured."
done

echo "=== Redis secrets engine ready ==="
```

---

### Neo4j secrets engine

```bash
#!/usr/bin/env bash
# scripts/vault/configure_neo4j_secrets.sh
# Neo4j uses the generic database plugin; roles issue native Neo4j user credentials.
set -euo pipefail

MOUNT="database/neo4j"

vault secrets enable -path="$MOUNT" database 2>/dev/null || echo "  Already enabled."

vault write "$MOUNT/config/contextiq-neo4j" \
  plugin_name   = "neo4j-database-plugin" \
  allowed_roles = "agent-worker" \
  url           = "bolt://neo4j.contextiq-data.svc.cluster.local:7687" \
  username      = "${NEO4J_ADMIN_USER}" \
  password      = "${NEO4J_ADMIN_PASSWORD}"

vault write "$MOUNT/roles/agent-worker" \
  db_name             = "contextiq-neo4j" \
  creation_statements = '{"roles":[{"role":"reader"}]}' \
  default_ttl         = "1h" \
  max_ttl             = "2h"

echo "=== Neo4j secrets engine ready ==="
```

---

### Qdrant credential rotation (static secret — no native plugin)

```bash
#!/usr/bin/env bash
# scripts/vault/configure_qdrant_secrets.sh
# Qdrant does not have a native Vault database plugin.
# We use the Vault KV v2 secrets engine to store the Qdrant API key
# and rotate it via a scheduled Vault Transform or manual operator rotation.
# The Vault Agent sidecar still renders the key into pods, maintaining
# the same injection pattern as the database secrets engines.
set -euo pipefail

MOUNT="secret"

# Enable KV v2 at secret/ if not already enabled
vault secrets enable -path="$MOUNT" kv-v2 2>/dev/null || echo "  KV v2 already enabled."

# Write the Qdrant API key (operator provides value — never hard-coded)
vault kv put "$MOUNT/contextiq/qdrant/api-key" \
  api_key="${QDRANT_API_KEY}"

echo "=== Qdrant API key stored at $MOUNT/contextiq/qdrant/api-key ==="
echo "NOTE: Rotate manually or via Vault Transform. Re-run this script after rotation."
```

---

### Per-service Vault policies

```bash
#!/usr/bin/env bash
# scripts/vault/configure_policies.sh
# Idempotent — each policy write is an upsert.
set -euo pipefail

echo "=== Writing Vault policies ==="

# mcp-gateway policy: PostgreSQL + Redis read credentials + connector secrets
vault policy write mcp-gateway - <<'EOF'
# PostgreSQL dynamic credentials
path "database/postgres/creds/mcp-gateway" {
  capabilities = ["read"]
}
# Redis dynamic credentials
path "database/redis/creds/mcp-gateway" {
  capabilities = ["read"]
}
# OPA / Keycloak URLs (static KV)
path "secret/data/contextiq/keycloak/*" {
  capabilities = ["read"]
}
# Connector vault_path secrets (read only — connectors store their own paths)
path "secret/data/contextiq/connectors/*" {
  capabilities = ["read"]
}
EOF

vault policy write agent-worker - <<'EOF'
path "database/postgres/creds/agent-worker" { capabilities = ["read"] }
path "database/redis/creds/agent-worker"    { capabilities = ["read"] }
path "database/neo4j/creds/agent-worker"    { capabilities = ["read"] }
path "secret/data/contextiq/qdrant/api-key" { capabilities = ["read"] }
EOF

vault policy write indexing-service - <<'EOF'
path "database/postgres/creds/indexing-service" { capabilities = ["read"] }
path "secret/data/contextiq/qdrant/api-key"     { capabilities = ["read"] }
EOF

vault policy write admin-api - <<'EOF'
path "database/postgres/creds/admin-api" { capabilities = ["read"] }
path "database/redis/creds/mcp-gateway"  { capabilities = ["read"] }
path "secret/data/contextiq/keycloak/*"  { capabilities = ["read"] }
path "secret/data/contextiq/entra_id"    { capabilities = ["read"] }
path "secret/data/contextiq/saml_idp"    { capabilities = ["read"] }
EOF

vault policy write keycloak - <<'EOF'
path "database/postgres/creds/keycloak" { capabilities = ["read"] }
path "secret/data/contextiq/keycloak/*" { capabilities = ["read"] }
EOF

echo "=== Vault policies written ==="
```

---

### Kubernetes auth roles (one per service account)

```bash
#!/usr/bin/env bash
# scripts/vault/configure_k8s_auth_roles.sh
# Each role binds a Kubernetes ServiceAccount to a Vault policy.
set -euo pipefail

echo "=== Configuring Kubernetes auth roles ==="

declare -A ROLES=(
  ["mcp-gateway"]="contextiq-gateway:mcp-gateway:mcp-gateway"
  ["agent-worker"]="contextiq-agents:agent-worker:agent-worker"
  ["indexing-service"]="contextiq-agents:indexing-service:indexing-service"
  ["admin-api"]="contextiq-admin:admin-api:admin-api"
  ["keycloak"]="keycloak:vault:keycloak"
)

for VAULT_ROLE in "${!ROLES[@]}"; do
  IFS=":" read -r NAMESPACE SA_NAME POLICY <<< "${ROLES[$VAULT_ROLE]}"
  vault write "auth/kubernetes/role/$VAULT_ROLE" \
    bound_service_account_names      = "$SA_NAME" \
    bound_service_account_namespaces = "$NAMESPACE" \
    policies                         = "$POLICY" \
    ttl                              = "1h"    # AC-4: agent token TTL
  echo "  Role $VAULT_ROLE bound to $NAMESPACE/$SA_NAME → policy $POLICY"
done

echo "=== Kubernetes auth roles configured ==="
```

## Acceptance Criteria

- [ ] `vault secrets list` shows `database/postgres/`, `database/redis/`, `database/neo4j/`, `secret/` all enabled (AC-2)
- [ ] `vault read database/postgres/creds/mcp-gateway` returns a unique `username`/`password` with `lease_duration: 1h` (AC-2, AC-4)
- [ ] Repeated calls to `vault read database/postgres/creds/mcp-gateway` return different credentials each time (dynamic) (AC-2)
- [ ] All scripts are idempotent — running twice does not error or duplicate roles (AC-2)
- [ ] `vault policy read mcp-gateway` shows only the paths the gateway service needs — no over-privileged access (AC-4, OWASP A01)
- [ ] `vault write auth/kubernetes/role/mcp-gateway` binds correctly to `contextiq-gateway` namespace service account

## Dependencies

- TASK-US047-01 — Vault initialised, Kubernetes auth enabled (`init_vault.sh` complete)
- EP-DATA-001 — PostgreSQL, Redis, Neo4j running and reachable from `contextiq-security`
- Admin credentials for each database must be available in the environment before running configuration scripts (not stored in code)

## Definition of Done

- [ ] All five `configure_*.sh` scripts run without error in staging
- [ ] `vault read database/postgres/creds/mcp-gateway` returns credentials valid for PostgreSQL login
- [ ] `psql "host=... user=<dynamic_user> password=<dynamic_pass>"` connects successfully
