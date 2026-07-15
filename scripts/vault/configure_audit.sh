#!/usr/bin/env bash
# scripts/vault/configure_audit.sh
# Enable Vault audit devices on the active Vault node.
# Each Vault pod writes to /vault/audit/audit.log, which Promtail collects.
# Idempotent — safe to re-run.
#
# Prerequisites: VAULT_ADDR, VAULT_TOKEN set before running.
#
# AC-6: NEVER log raw secret values — audit log entries contain HMAC-hashed
# token/secret values only (log_raw=false is the default and is explicitly set).
set -euo pipefail

echo "=== Enabling Vault audit devices ==="

# File audit device: JSON lines written to /vault/audit/audit.log
# The path= flag sets the mount name in Vault (must be unique); file_path= is the disk path.
vault audit enable \
  -path=file \
  file \
  file_path=/vault/audit/audit.log \
  log_raw=false \
  format=json \
  2>/dev/null || echo "  File audit device already enabled."

# Syslog audit device: redundant channel so audit events survive a log rotation race
vault audit enable syslog \
  2>/dev/null || echo "  Syslog audit device already enabled."

echo "=== Vault audit devices configured ==="
echo "  File audit path: /vault/audit/audit.log (collected by Promtail)"
echo "  Syslog audit:    enabled as redundant channel"
echo ""
echo "Verify with: vault audit list"
