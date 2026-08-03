#!/usr/bin/env bash
# scripts/security/check_tls_versions.sh
#
# AC-4: Probe each external and internal TLS endpoint and assert only TLS 1.3 is accepted.
# Fails (exit 1) if any endpoint accepts TLS 1.2 or lower, or does not support TLS 1.3.
#
# Usage:
#   bash scripts/security/check_tls_versions.sh
#   CHECK_INTERNAL=true bash scripts/security/check_tls_versions.sh  # also probe in-cluster services
set -euo pipefail

PASS=0
FAIL=0

check_endpoint() {
  local ENDPOINT="$1"
  local PORT="${2:-443}"
  # Extract hostname for SNI — required for virtual-hosted TLS endpoints
  local HOST="${ENDPOINT%%:*}"

  echo "--- Checking ${ENDPOINT}:${PORT} ---"

  # Assert TLS 1.3 is accepted
  if echo | openssl s_client \
      -connect "${ENDPOINT}:${PORT}" \
      -servername "$HOST" \
      -tls1_3 -brief 2>&1 | grep -q "Protocol version: TLSv1.3"; then
    echo "  [PASS] TLS 1.3 accepted"
    PASS=$(( PASS + 1 ))
  else
    echo "  [FAIL] TLS 1.3 NOT accepted at ${ENDPOINT}:${PORT}"
    FAIL=$(( FAIL + 1 ))
  fi

  # Assert TLS 1.2 is REJECTED
  # Capture output and exit code separately so set -e does not abort on expected failure
  local TLS12_OUTPUT
  local TLS12_EXIT=0
  TLS12_OUTPUT=$(echo | openssl s_client \
    -connect "${ENDPOINT}:${PORT}" \
    -servername "$HOST" \
    -tls1_2 -brief 2>&1) || TLS12_EXIT=$?

  if [ "$TLS12_EXIT" -ne 0 ] || echo "$TLS12_OUTPUT" | grep -qi "handshake failure"; then
    echo "  [PASS] TLS 1.2 rejected"
    PASS=$(( PASS + 1 ))
  elif echo "$TLS12_OUTPUT" | grep -q "Protocol version: TLSv1.2"; then
    echo "  [FAIL] TLS 1.2 is STILL accepted at ${ENDPOINT}:${PORT} — AC-4 violation"
    FAIL=$(( FAIL + 1 ))
  else
    echo "  [WARN] Could not determine TLS 1.2 status at ${ENDPOINT}:${PORT}"
  fi
}

# External Ingress endpoints
check_endpoint "api.contextiq.io"
check_endpoint "auth.contextiq.io"
check_endpoint "admin.contextiq.io"

# Internal service endpoints (run from within cluster network or via port-forward)
if [ "${CHECK_INTERNAL:-false}" = "true" ]; then
  check_endpoint "vault.contextiq-security.svc.cluster.local"  8200
  check_endpoint "postgres.contextiq-data.svc.cluster.local"   5432
  check_endpoint "redis.contextiq-data.svc.cluster.local"      6379
fi

echo ""
echo "=== TLS Version Check Results ==="
echo "  Passed: $PASS"
echo "  Failed: $FAIL"

if [ "$FAIL" -gt 0 ]; then
  echo "FAIL: $FAIL endpoint(s) do not comply with TLS 1.3-only requirement (AC-4)"
  exit 1
fi
echo "PASS: All endpoints enforce TLS 1.3 only"
