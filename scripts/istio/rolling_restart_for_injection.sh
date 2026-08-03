#!/usr/bin/env bash
# scripts/istio/rolling_restart_for_injection.sh
#
# Restarts all Deployments and StatefulSets in contextiq-* namespaces so that
# Istio's mutating webhook injects the Envoy sidecar into every new pod.
#
# Prerequisites:
#   1. Istio control plane deployed (istiod Running in istio-system)
#   2. Namespace labels applied:  kubectl apply -f k8s/namespaces/namespace-labels.yaml
#   3. PeerAuthentication applied: kubectl apply -f k8s/istio/peer-authentication.yaml
#   4. All workloads healthy before restart — do NOT run during initial cluster bootstrap
#
# After this script completes, verify injection with:
#   kubectl get pods -n contextiq-gateway -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].name}{"\n"}{end}'
set -euo pipefail

NAMESPACES=(
  contextiq-data
  contextiq-agents
  contextiq-gateway
  contextiq-admin
  contextiq-security
  contextiq-observability
  contextiq-infra
)

for NS in "${NAMESPACES[@]}"; do
  echo "=== Rolling restart in $NS ==="
  if kubectl get deployment -n "$NS" -o name 2>/dev/null | grep -q .; then
    kubectl rollout restart deployment -n "$NS"
  else
    echo "  No Deployments in $NS"
  fi

  if kubectl get statefulset -n "$NS" -o name 2>/dev/null | grep -q .; then
    kubectl rollout restart statefulset -n "$NS"
  else
    echo "  No StatefulSets in $NS"
  fi
done

echo ""
echo "=== Waiting for all rollouts to complete ==="
for NS in "${NAMESPACES[@]}"; do
  while IFS= read -r RESOURCE; do
    [ -z "$RESOURCE" ] && continue
    kubectl rollout status "$RESOURCE" -n "$NS" --timeout=300s
  done < <(kubectl get deploy,statefulset -n "$NS" -o name 2>/dev/null)
done

echo "=== Done — all workloads restarted with Istio sidecars ==="
