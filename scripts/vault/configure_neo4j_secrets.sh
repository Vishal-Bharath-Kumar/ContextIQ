#!/usr/bin/env bash
# scripts/vault/configure_neo4j_secrets.sh
# Enable and configure the Vault database secrets engine for Neo4j.
# Uses the community neo4j-database-plugin; roles issue native Neo4j user credentials.
# Idempotent — safe to re-run.
#
# Prerequisites:
#   VAULT_ADDR, VAULT_TOKEN — set before running
#   NEO4J_ADMIN_USER        — Neo4j admin username
#   NEO4J_ADMIN_PASSWORD    — Neo4j admin password
#
# NOTE: neo4j-database-plugin is a community Vault plugin. Register it with
#   vault plugin register -sha256=<sha> database neo4j-database-plugin
# before running this script if it is not already in the Vault plugin catalog.
set -euo pipefail

MOUNT="database/neo4j"

echo "=== Enabling Neo4j secrets engine at $MOUNT ==="
vault secrets enable -path="$MOUNT" database 2>/dev/null || echo "  Already enabled."

echo "=== Configuring Neo4j connection ==="
vault write "$MOUNT/config/contextiq-neo4j" \
  plugin_name   = "neo4j-database-plugin" \
  allowed_roles = "agent-worker" \
  url           = "bolt://neo4j.contextiq-data.svc.cluster.local:7687" \
  username      = "${NEO4J_ADMIN_USER}" \
  password      = "${NEO4J_ADMIN_PASSWORD}"

echo "=== Configuring dynamic role agent-worker (TTL: 1h / max 2h) ==="
# AC-4: reader role only — agent-worker has read access to the knowledge graph
vault write "$MOUNT/roles/agent-worker" \
  db_name             = "contextiq-neo4j" \
  creation_statements = '{"roles":[{"role":"reader"}]}' \
  default_ttl         = "1h" \
  max_ttl             = "2h"

echo "=== Neo4j secrets engine ready ==="
