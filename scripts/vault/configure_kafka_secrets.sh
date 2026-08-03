#!/usr/bin/env bash
# scripts/vault/configure_kafka_secrets.sh
# Store Kafka broker inter-broker credentials and per-service client credentials
# in Vault KV v2.
# Run ONCE during initial Vault setup (TASK-US047-02 extension).
# Re-running will overwrite existing passwords and break active broker connections.
set -euo pipefail

echo "=== Configuring Kafka secrets in Vault ==="

# Inter-broker SCRAM-SHA-512 credentials
vault kv put secret/contextiq/kafka/broker \
  username="kafka-inter-broker" \
  password="${KAFKA_INTER_BROKER_PASSWORD:?KAFKA_INTER_BROKER_PASSWORD required}"

echo "  Inter-broker credentials stored."

# Per-service client credentials (one Vault path per service)
for SVC in mcp-gateway indexing-service agent-worker admin-api; do
  CLIENT_PASSWORD="${SVC}_$(openssl rand -hex 16)"
  vault kv put "secret/contextiq/kafka/clients/${SVC}" \
    username="${SVC}" \
    password="${CLIENT_PASSWORD}"
  echo "  Client credentials stored for ${SVC}"
done

echo "=== Kafka secrets configured ==="
