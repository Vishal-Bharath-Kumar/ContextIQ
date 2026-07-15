#!/usr/bin/env bash
# scripts/vault/configure_redis_secrets.sh
# Enable and configure the Vault database secrets engine for Redis.
# Uses the redis-database-plugin to issue ACL-based short-lived credentials.
# Idempotent — safe to re-run.
#
# Prerequisites:
#   VAULT_ADDR, VAULT_TOKEN — set before running
#   REDIS_ADMIN_USER        — Redis admin username (ACL enabled)
#   REDIS_ADMIN_PASSWORD    — Redis admin password
set -euo pipefail

MOUNT="database/redis"

echo "=== Enabling Redis secrets engine at $MOUNT ==="
vault secrets enable -path="$MOUNT" database 2>/dev/null || echo "  Already enabled."

echo "=== Configuring Redis connection ==="
vault write "$MOUNT/config/contextiq-redis" \
  plugin_name   = "redis-database-plugin" \
  allowed_roles = "mcp-gateway,agent-worker" \
  host          = "redis.contextiq-data.svc.cluster.local" \
  port          = 6379 \
  username      = "${REDIS_ADMIN_USER}" \
  password      = "${REDIS_ADMIN_PASSWORD}" \
  tls           = true

echo "=== Configuring dynamic roles (TTL: 1h / max 2h) ==="
# AC-4: credentials renewed by Vault Agent sidecar before expiry
for ROLE in mcp-gateway agent-worker; do
  vault write "$MOUNT/roles/$ROLE" \
    db_name             = "contextiq-redis" \
    creation_statements = "{\"rules\":[{\"rule_type\":\"commandkeypattern\",\"rule\":\"allcommands~*\"}]}" \
    default_ttl         = "1h" \
    max_ttl             = "2h"
  echo "  Redis role $ROLE configured."
done

echo "=== Redis secrets engine ready ==="
