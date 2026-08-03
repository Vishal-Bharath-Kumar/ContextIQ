#!/usr/bin/env bash
# scripts/security/verify_encryption_at_rest.sh
#
# AC-5: Asserts that all PVs use the encrypted StorageClass and MinIO SSE is active.
# Requires: kubectl, aws CLI, and mc (MinIO client) on PATH.
# Run from within the cluster or with KUBECONFIG + AWS_* env vars set.
set -euo pipefail

PASS=0
FAIL=0
ENCRYPTED_CLASS="contextiq-encrypted-gp3"

echo "=== Verifying PV encryption ==="

# Format: "namespace:pvc-name"
PVCS=(
  "contextiq-data:data-postgres-0"
  "contextiq-data:data-redis-0"
  "contextiq-data:data-neo4j-0"
  "contextiq-data:qdrant-storage-qdrant-0"
  "contextiq-infra:data-minio-0"
)

for ENTRY in "${PVCS[@]}"; do
  NS="${ENTRY%%:*}"
  PVC="${ENTRY##*:}"

  SC=$(kubectl get pvc "$PVC" -n "$NS" \
    -o jsonpath='{.spec.storageClassName}' 2>/dev/null || echo "NOT_FOUND")

  if [ "$SC" = "$ENCRYPTED_CLASS" ]; then
    echo "  [PASS] $NS/$PVC uses $ENCRYPTED_CLASS"
    PASS=$(( PASS + 1 ))
  else
    echo "  [FAIL] $NS/$PVC uses '$SC' — expected '$ENCRYPTED_CLASS'"
    FAIL=$(( FAIL + 1 ))
  fi

  # Verify the backing EBS volume has Encrypted=true via AWS CLI
  PV_NAME=$(kubectl get pvc "$PVC" -n "$NS" \
    -o jsonpath='{.spec.volumeName}' 2>/dev/null || echo "")
  if [ -n "$PV_NAME" ]; then
    VOLUME_ID=$(kubectl get pv "$PV_NAME" \
      -o jsonpath='{.spec.csi.volumeHandle}' 2>/dev/null || echo "")
    if [ -n "$VOLUME_ID" ]; then
      # AWS CLI --output text returns "True" / "False" (Python-style boolean strings)
      ENCRYPTED=$(aws ec2 describe-volumes --volume-ids "$VOLUME_ID" \
        --query 'Volumes[0].Encrypted' --output text 2>/dev/null || echo "UNKNOWN")
      if [ "$ENCRYPTED" = "True" ]; then
        echo "  [PASS] EBS volume $VOLUME_ID is encrypted"
        PASS=$(( PASS + 1 ))
      else
        echo "  [FAIL] EBS volume $VOLUME_ID encrypted=$ENCRYPTED — AES-256 not confirmed"
        FAIL=$(( FAIL + 1 ))
      fi
    fi
  fi
done

echo ""
echo "=== Verifying MinIO SSE-S3 ==="

BUCKETS=(contextiq-traces contextiq-audit-archive contextiq-models contextiq-embeddings)
for BUCKET in "${BUCKETS[@]}"; do
  # mc encrypt info outputs "SSE-S3" or "sse-s3" depending on version; match case-insensitively
  STATUS=$(mc encrypt info "contextiq/${BUCKET}" 2>/dev/null | grep -i "sse-s3" || echo "DISABLED")
  if echo "$STATUS" | grep -qi "sse-s3"; then
    echo "  [PASS] $BUCKET has SSE-S3 enabled"
    PASS=$(( PASS + 1 ))
  else
    echo "  [FAIL] $BUCKET does not have SSE-S3 enabled"
    FAIL=$(( FAIL + 1 ))
  fi
done

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] || { echo "FAIL: Encryption at rest not fully enforced (AC-5)"; exit 1; }
echo "PASS: All data stores have encryption at rest (AC-5)"
