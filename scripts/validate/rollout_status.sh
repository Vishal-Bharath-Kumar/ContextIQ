#!/usr/bin/env bash
# scripts/validate/rollout_status.sh
# AC-5: Wait for all Deployments and StatefulSets in contextiq-* namespaces
# to complete rollout. Exits non-zero if any rollout times out (300s).
set -euo pipefail

TIMEOUT=300
NAMESPACES=(
  contextiq-gateway
  contextiq-agents
  contextiq-data
  contextiq-admin
  contextiq-observability
  contextiq-security
  contextiq-infra
)

overall_exit=0

for ns in "${NAMESPACES[@]}"; do
  echo "=== Checking rollouts in namespace: $ns ==="

  # Deployments
  deployments=$(kubectl get deployments -n "$ns" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)
  for deploy in $deployments; do
    echo "  Waiting for deployment/$deploy ..."
    if ! kubectl rollout status deployment/"$deploy" -n "$ns" --timeout="${TIMEOUT}s"; then
      echo "  FAILED: deployment/$deploy did not roll out in ${TIMEOUT}s"
      overall_exit=1
    fi
  done

  # StatefulSets (PostgreSQL, Redis, MinIO nodes)
  statefulsets=$(kubectl get statefulsets -n "$ns" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)
  for sts in $statefulsets; do
    echo "  Waiting for statefulset/$sts ..."
    if ! kubectl rollout status statefulset/"$sts" -n "$ns" --timeout="${TIMEOUT}s"; then
      echo "  FAILED: statefulset/$sts did not roll out in ${TIMEOUT}s"
      overall_exit=1
    fi
  done
done

if [ $overall_exit -eq 0 ]; then
  echo "All rollouts complete."
else
  echo "One or more rollouts failed — see output above."
fi
exit $overall_exit
