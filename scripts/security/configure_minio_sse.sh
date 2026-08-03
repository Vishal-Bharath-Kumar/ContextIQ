#!/usr/bin/env bash
# scripts/security/configure_minio_sse.sh
#
# AC-5: Enable MinIO SSE-S3 (AES-256) on all ContextIQ buckets.
#
# Prerequisites:
#   - mc (MinIO client) installed and on PATH
#   - Environment variables set (provided by Vault Agent sidecar — TASK-US047-03):
#       MINIO_ENDPOINT     (default: http://minio.contextiq-infra.svc.cluster.local:9000)
#       MINIO_ACCESS_KEY
#       MINIO_SECRET_KEY
set -euo pipefail

ALIAS="contextiq"
ENDPOINT="${MINIO_ENDPOINT:-http://minio.contextiq-infra.svc.cluster.local:9000}"

echo "=== Configuring MinIO SSE-S3 ==="

# Register MinIO alias (idempotent — overwrites if already set)
mc alias set "$ALIAS" "$ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" --api s3v4

BUCKETS=(
  contextiq-traces          # OTLP trace storage
  contextiq-audit-archive   # Audit log archive (TASK-US044-03)
  contextiq-models          # Model artefacts
  contextiq-embeddings      # Vector embedding exports
)

for BUCKET in "${BUCKETS[@]}"; do
  # Create bucket if it does not exist
  mc mb --ignore-existing "${ALIAS}/${BUCKET}"

  # AC-5: Enable SSE-S3 (AES-256 encryption at object level)
  mc encrypt set SSE-S3 "${ALIAS}/${BUCKET}"
  echo "  SSE-S3 enabled on $BUCKET"

  # Versioning: enabled to allow point-in-time recovery
  mc version enable "${ALIAS}/${BUCKET}"
  echo "  Versioning enabled on $BUCKET"
done

echo "=== MinIO SSE-S3 configuration complete ==="
