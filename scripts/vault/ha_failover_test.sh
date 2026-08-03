#!/usr/bin/env bash
# scripts/vault/ha_failover_test.sh
# AC-7: Delete the Vault leader pod; assert a new leader is elected within 30 s.
#
# Prerequisites:
#   - kubectl access to contextiq-security namespace
#   - vault CLI with VAULT_ADDR pointed at the Vault internal service
#   - VAULT_ADDR and VAULT_TOKEN set in the environment
set -euo pipefail

NAMESPACE="contextiq-security"
MAX_RECOVERY_SECONDS=30

echo "=== Vault HA Failover Test ==="
echo "Target: new leader elected within ${MAX_RECOVERY_SECONDS}s after leader pod deletion"

# ──────────────────────────────────────────────────────────────────────────────
# Identify the current leader pod
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "--- Identifying current leader ---"
LEADER_POD=""
for POD in vault-0 vault-1 vault-2; do
  STATUS=$(kubectl exec -n "$NAMESPACE" "$POD" -- vault status -format=json 2>/dev/null \
    || echo '{"is_self":false}')
  if echo "$STATUS" | jq -e '.sealed == false and .is_self == true' >/dev/null 2>&1; then
    LEADER_POD="$POD"
    break
  fi
done

if [ -z "$LEADER_POD" ]; then
  echo "ERROR: Could not identify leader pod. Is Vault running and unsealed?"
  exit 1
fi
echo "Current leader: $LEADER_POD"

# ──────────────────────────────────────────────────────────────────────────────
# Pre-failover health snapshot
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "--- Pre-failover health check ---"
kubectl exec -n "$NAMESPACE" "$LEADER_POD" -- vault status -format=json \
  | jq '{sealed, ha_enabled, is_self, leader_address}'

# ──────────────────────────────────────────────────────────────────────────────
# Force-delete the leader pod to trigger failover
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "--- Deleting leader pod $LEADER_POD ---"
START_EPOCH=$(date +%s)
kubectl delete pod "$LEADER_POD" -n "$NAMESPACE" --grace-period=0 --force

# ──────────────────────────────────────────────────────────────────────────────
# Poll remaining pods for a new active leader
# ──────────────────────────────────────────────────────────────────────────────
echo "--- Polling for new leader (timeout: ${MAX_RECOVERY_SECONDS}s) ---"
while true; do
  ELAPSED=$(( $(date +%s) - START_EPOCH ))
  if [ $ELAPSED -ge $MAX_RECOVERY_SECONDS ]; then
    break
  fi

  for STANDBY_POD in vault-0 vault-1 vault-2; do
    [ "$STANDBY_POD" = "$LEADER_POD" ] && continue   # skip the deleted pod
    STATUS=$(kubectl exec -n "$NAMESPACE" "$STANDBY_POD" -- vault status -format=json 2>/dev/null \
      || continue)
    if echo "$STATUS" | jq -e '.sealed == false and .is_self == true' >/dev/null 2>&1; then
      echo ""
      echo "SUCCESS: New leader $STANDBY_POD elected after ${ELAPSED}s (limit: ${MAX_RECOVERY_SECONDS}s)"
      kubectl exec -n "$NAMESPACE" "$STANDBY_POD" -- vault status -format=json \
        | jq '{sealed, is_self, leader_address}'
      exit 0
    fi
  done

  printf "  Waiting... %ds elapsed\r" "$ELAPSED"
  sleep 2
done

echo ""
echo "FAIL: No leader elected within ${MAX_RECOVERY_SECONDS}s"
exit 1
