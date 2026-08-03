#!/usr/bin/env bash
# scripts/validate/network_policy_check.sh
# AC-4: Spot-check that default-deny is enforced and allowed flows work.
# Uses a transient busybox test pod in each namespace.
set -euo pipefail

echo "=== Network policy connectivity check ==="

# Helper: run nc from a pod and expect success (0) or failure (non-zero)
check_connectivity() {
  local from_ns="$1" to_host="$2" to_port="$3" expect_success="$4" label="$5"
  local result
  result=$(kubectl run "netcheck-$$" \
    --image=busybox:1.36 \
    --restart=Never \
    --rm \
    --namespace="$from_ns" \
    --command -- \
    sh -c "nc -zv -w 3 $to_host $to_port 2>&1; echo exit:\$?" \
    2>/dev/null || true)

  if echo "$result" | grep -q "exit:0"; then
    if [ "$expect_success" = "true" ]; then
      echo "  PASS: $label (allowed as expected)"
    else
      echo "  FAIL: $label (should be DENIED but connection succeeded)"
      return 1
    fi
  else
    if [ "$expect_success" = "false" ]; then
      echo "  PASS: $label (denied as expected)"
    else
      echo "  FAIL: $label (should be ALLOWED but connection failed)"
      return 1
    fi
  fi
}

# AC-4: allowed flow — gateway → data on PostgreSQL port
check_connectivity \
  "contextiq-gateway" \
  "postgres.contextiq-data.svc.cluster.local" \
  "5432" \
  "true" \
  "gateway→data:5432 (PostgreSQL)"

# AC-4: denied flow — admin → data (no allow rule exists)
check_connectivity \
  "contextiq-admin" \
  "postgres.contextiq-data.svc.cluster.local" \
  "5432" \
  "false" \
  "admin→data:5432 (should be denied)"

# AC-4: allowed flow — agents → infra on Kafka port
check_connectivity \
  "contextiq-agents" \
  "kafka.contextiq-infra.svc.cluster.local" \
  "9092" \
  "true" \
  "agents→infra:9092 (Kafka)"

echo "=== Network policy check complete ==="
