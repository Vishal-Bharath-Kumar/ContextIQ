# TASK-US048-04 — Encryption at Rest: PostgreSQL, Qdrant, Neo4j, Redis, and MinIO

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US048-04 |
| User Story | US-048 |
| Epic | EP-TECH-002 — Security Hardening & Secrets Management |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Ensure all five data stores store data on encrypted volumes with AES-256 (AC-5). The primary mechanism is a Kubernetes `StorageClass` that provisions encrypted EBS volumes (AWS `gp3` with `encrypted: "true"`). All `PersistentVolumeClaim` resources for PostgreSQL, Qdrant, Neo4j, Redis, and MinIO are patched to reference this `StorageClass`. MinIO receives an additional application-level server-side encryption (SSE-S3 AES-256) layer so objects are encrypted at the object store level independent of disk encryption. A validation script confirms all PVs are backed by encrypted volumes and all MinIO buckets have SSE enabled.

## Implementation Details

**Technology:** Kubernetes CSI driver for EBS, AWS KMS CMK, MinIO SSE-S3, Helm patches

**File locations:**
- `k8s/storage/encrypted-storage-class.yaml` — `StorageClass` with `encrypted: "true"` + KMS CMK
- `k8s/postgres/statefulset-patch.yaml` — PVC `storageClassName` patch
- `k8s/redis/statefulset-patch.yaml` — PVC `storageClassName` patch
- `k8s/neo4j/statefulset-patch.yaml` — PVC `storageClassName` patch
- `k8s/qdrant/statefulset-patch.yaml` — PVC `storageClassName` patch
- `k8s/minio/statefulset-patch.yaml` — PVC `storageClassName` patch
- `scripts/security/configure_minio_sse.sh` — enable MinIO SSE-S3 on all buckets
- `scripts/security/verify_encryption_at_rest.sh` — validation script

---

### Encrypted StorageClass (AWS EBS CSI driver)

```yaml
# k8s/storage/encrypted-storage-class.yaml
# AC-5: AES-256 encryption for all data store PVs via AWS EBS encryption.
# The KMS CMK alias/contextiq-data-encryption is used so the key is managed
# separately from the cluster default key.
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: contextiq-encrypted-gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "false"    # opt-in per PVC; not cluster-wide default
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer    # provision in the same AZ as the pod
reclaimPolicy: Retain    # RETAIN: data survives PVC deletion — prevents accidental data loss
allowVolumeExpansion: true
parameters:
  type:      gp3
  iops:      "3000"
  throughput: "125"
  encrypted: "true"    # AC-5: EBS volume encrypted with AES-256
  kmsKeyId:  "alias/contextiq-data-encryption"    # CMK managed outside the cluster
```

---

### PVC patches — reference the encrypted StorageClass

Each data store's StatefulSet or Deployment uses a VolumeClaimTemplate or PVC that must reference `contextiq-encrypted-gp3`. Apply as Kustomize patches so the base chart is unchanged.

```yaml
# k8s/postgres/statefulset-patch.yaml
# Kustomize strategic merge patch — sets storageClassName on PostgreSQL PVC
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: contextiq-data
spec:
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        storageClassName: contextiq-encrypted-gp3
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 100Gi
```

```yaml
# k8s/redis/statefulset-patch.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: contextiq-data
spec:
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        storageClassName: contextiq-encrypted-gp3
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 20Gi
```

```yaml
# k8s/neo4j/statefulset-patch.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: neo4j
  namespace: contextiq-data
spec:
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        storageClassName: contextiq-encrypted-gp3
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 50Gi
```

```yaml
# k8s/qdrant/statefulset-patch.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: qdrant
  namespace: contextiq-data
spec:
  volumeClaimTemplates:
    - metadata:
        name: qdrant-storage
      spec:
        storageClassName: contextiq-encrypted-gp3
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 50Gi
```

```yaml
# k8s/minio/statefulset-patch.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: minio
  namespace: contextiq-infra
spec:
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        storageClassName: contextiq-encrypted-gp3
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 500Gi
```

---

### MinIO application-level SSE-S3 (AES-256)

MinIO supports server-side encryption independent of the underlying disk encryption. Enabling SSE-S3 provides an additional encryption layer at the object level.

```bash
#!/usr/bin/env bash
# scripts/security/configure_minio_sse.sh
# AC-5: Enable MinIO SSE-S3 (AES-256) on all ContextIQ buckets.
# Requires: mc (MinIO client) installed and MINIO_ENDPOINT, MINIO_ACCESS_KEY,
# MINIO_SECRET_KEY set as environment variables (provided by Vault Agent sidecar
# after TASK-US047-03 is applied).
set -euo pipefail

ALIAS="contextiq"
ENDPOINT="${MINIO_ENDPOINT:-http://minio.contextiq-infra.svc.cluster.local:9000}"

echo "=== Configuring MinIO SSE-S3 ==="

# Register MinIO alias
mc alias set "$ALIAS" "$ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" --api S3v4

# Enable encryption for all ContextIQ buckets
BUCKETS=(
  contextiq-traces        # OTLP trace storage
  contextiq-audit-archive # Audit log archive (TASK-US044-03)
  contextiq-models        # Model artefacts
  contextiq-embeddings    # Vector embedding exports
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
```

---

### Encryption at rest validation script

```bash
#!/usr/bin/env bash
# scripts/security/verify_encryption_at_rest.sh
# AC-5: Asserts that all PVs use the encrypted StorageClass and MinIO SSE is active.
set -euo pipefail

PASS=0
FAIL=0
ENCRYPTED_CLASS="contextiq-encrypted-gp3"

echo "=== Verifying PV encryption ==="

# Check each PVC uses the encrypted storage class
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
  SC=$(kubectl get pvc "$PVC" -n "$NS" -o jsonpath='{.spec.storageClassName}' 2>/dev/null || echo "NOT_FOUND")
  if [ "$SC" = "$ENCRYPTED_CLASS" ]; then
    echo "  [PASS] $NS/$PVC uses $ENCRYPTED_CLASS"
    PASS=$(( PASS + 1 ))
  else
    echo "  [FAIL] $NS/$PVC uses '$SC' — expected '$ENCRYPTED_CLASS'"
    FAIL=$(( FAIL + 1 ))
  fi

  # Verify the backing EBS volume has Encrypted=true via AWS CLI
  PV_NAME=$(kubectl get pvc "$PVC" -n "$NS" -o jsonpath='{.spec.volumeName}' 2>/dev/null || echo "")
  if [ -n "$PV_NAME" ]; then
    VOLUME_ID=$(kubectl get pv "$PV_NAME" -o jsonpath='{.spec.csi.volumeHandle}' 2>/dev/null || echo "")
    if [ -n "$VOLUME_ID" ]; then
      ENCRYPTED=$(aws ec2 describe-volumes --volume-ids "$VOLUME_ID" \
        --query 'Volumes[0].Encrypted' --output text 2>/dev/null || echo "UNKNOWN")
      if [ "$ENCRYPTED" = "True" ]; then
        echo "  [PASS] EBS volume $VOLUME_ID is encrypted"
        PASS=$(( PASS + 1 ))
      else
        echo "  [FAIL] EBS volume $VOLUME_ID encrypted=$ENCRYPTED"
        FAIL=$(( FAIL + 1 ))
      fi
    fi
  fi
done

echo ""
echo "=== Verifying MinIO SSE-S3 ==="

BUCKETS=(contextiq-traces contextiq-audit-archive contextiq-models contextiq-embeddings)
for BUCKET in "${BUCKETS[@]}"; do
  STATUS=$(mc encrypt info "contextiq/$BUCKET" 2>/dev/null | grep -i "SSE-S3" || echo "DISABLED")
  if echo "$STATUS" | grep -qi "SSE-S3"; then
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
```

## Acceptance Criteria

- [x] `kubectl get storageclass contextiq-encrypted-gp3 -o yaml | grep encrypted` shows `encrypted: "true"` (AC-5)
- [x] All 5 data store PVCs (`data-postgres-0`, `data-redis-0`, `data-neo4j-0`, `qdrant-storage-qdrant-0`, `data-minio-0`) reference `contextiq-encrypted-gp3` (AC-5)
- [x] `aws ec2 describe-volumes --volume-ids <pvId>` returns `"Encrypted": true` for all data store EBS volumes (AC-5)
- [x] `mc encrypt info contextiq/contextiq-audit-archive` shows `SSE-S3` — MinIO object-level AES-256 active (AC-5)
- [x] `scripts/security/verify_encryption_at_rest.sh` exits 0 (AC-5)

## Dependencies

- TASK-US045-01 — `contextiq-data` and `contextiq-infra` namespaces must exist
- AWS KMS CMK `alias/contextiq-data-encryption` must be provisioned before StorageClass is applied
- AWS EBS CSI driver must be installed in the cluster (standard EKS managed add-on)
- EP-DATA-001 — data store StatefulSets must already exist; patches are applied on top of running resources

## Definition of Done

- [x] `kubectl apply -f k8s/storage/encrypted-storage-class.yaml` creates the StorageClass
- [x] StatefulSet patches applied; pods restarted on new encrypted PVs without data loss
- [x] `configure_minio_sse.sh` runs without error in staging; all 4 buckets show SSE-S3 enabled
- [x] `verify_encryption_at_rest.sh` exits 0 in staging
