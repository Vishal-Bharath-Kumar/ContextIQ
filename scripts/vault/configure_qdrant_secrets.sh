#!/usr/bin/env bash
# scripts/vault/configure_qdrant_secrets.sh
# Qdrant does not have a native Vault database plugin.
# Stores the Qdrant API key in the Vault KV v2 engine so the Vault Agent
# sidecar can render it into pods using the same injection pattern as the
# dynamic database engines. Rotate by re-running this script with the new key.
# Idempotent — safe to re-run (kv put is an upsert).
#
# Prerequisites:
#   VAULT_ADDR, VAULT_TOKEN — set before running
#   QDRANT_API_KEY          — Qdrant API key (provided by operator; never hard-coded)
set -euo pipefail

MOUNT="secret"

echo "=== Enabling KV v2 secrets engine at $MOUNT ==="
vault secrets enable -path="$MOUNT" kv-v2 2>/dev/null || echo "  KV v2 already enabled."

echo "=== Writing Qdrant API key to $MOUNT/contextiq/qdrant/api-key ==="
vault kv put "$MOUNT/contextiq/qdrant/api-key" \
  api_key="${QDRANT_API_KEY}"

echo ""
echo "=== Qdrant API key stored at $MOUNT/contextiq/qdrant/api-key ==="
echo "NOTE: Qdrant credentials are static. Rotate by:"
echo "  1. Generating a new API key in the Qdrant admin UI"
echo "  2. Re-running this script with the new QDRANT_API_KEY value"
echo "  3. Restarting agent-worker pods so Vault Agent fetches the new version"
