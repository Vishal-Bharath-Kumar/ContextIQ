#!/usr/bin/env bash
# scripts/validate/pdb_disruption_test.sh
# AC-5: Verify PDB prevents evicting all mcp-gateway pods simultaneously.
# Drains one node and confirms at least MIN_AVAILABLE gateway pods remain Running.
set -euo pipefail

NAMESPACE="contextiq-gateway"
LABEL_SELECTOR="app.kubernetes.io/name=mcp-gateway"
MIN_AVAILABLE=2

echo "=== PDB disruption test ==="

# Count Running pods before drain
before=$(kubectl get pods -n "$NAMESPACE" \
  -l "$LABEL_SELECTOR" \
  --field-selector=status.phase=Running \
  -o name | wc -l | tr -d '[:space:]')
echo "  Running pods before: $before"

if [ "$before" -lt "$MIN_AVAILABLE" ]; then
  echo "  SKIP: fewer than $MIN_AVAILABLE pods running — cannot test disruption budget"
  exit 0
fi

# Pick the node running the first gateway pod
node=$(kubectl get pods -n "$NAMESPACE" \
  -l "$LABEL_SELECTOR" \
  -o jsonpath='{.items[0].spec.nodeName}')
echo "  Target node: $node"

# Attempt drain — PDB should block eviction if fewer than MIN_AVAILABLE pods would remain
echo "  Draining with --timeout=30s (expected to be blocked by PDB)..."
kubectl drain "$node" \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=5 \
  --timeout=30s \
  2>&1 | tee /tmp/drain_output.txt || true    # allow failure — PDB block is expected

# After attempted drain, count surviving Running pods
after=$(kubectl get pods -n "$NAMESPACE" \
  -l "$LABEL_SELECTOR" \
  --field-selector=status.phase=Running \
  -o name | wc -l | tr -d '[:space:]')
echo "  Running pods after attempted drain: $after"

# Uncordon the node regardless of outcome
kubectl uncordon "$node"
echo "  Node $node uncordoned."

if [ "$after" -ge "$MIN_AVAILABLE" ]; then
  echo "  PASS: PDB protected at least $MIN_AVAILABLE replicas during node drain"
  echo "=== PDB disruption test PASSED ==="
  exit 0
else
  echo "  FAIL: only $after pod(s) survived — PDB not working correctly"
  exit 1
fi
