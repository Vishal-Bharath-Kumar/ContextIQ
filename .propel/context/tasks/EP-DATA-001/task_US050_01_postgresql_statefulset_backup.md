# TASK-US050-01 — PostgreSQL 15 StatefulSet, Persistent Volume, and Automated Daily Backup

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US050-01 |
| User Story | US-050 |
| Epic | EP-DATA-001 — Polyglot Data Store Setup |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Deploy PostgreSQL 15 as a Kubernetes `StatefulSet` in `contextiq-data` using the Bitnami `postgresql` Helm chart. The primary pod uses the `contextiq-encrypted-gp3` StorageClass (TASK-US048-04) for AES-256 encryption at rest. A `CronJob` runs `pg_basebackup` nightly and ships the archive to MinIO (`contextiq-postgres-backups` bucket); a lifecycle policy expires objects after 30 days (AC-1). Vault dynamic credentials (TASK-US047-02) are injected via the Agent sidecar; no static passwords appear in Kubernetes manifests. A `PodDisruptionBudget` with `minAvailable: 1` ensures planned maintenance does not exceed the 99.9% uptime target (AC-5 dependency).

## Implementation Details

**Technology:** Bitnami `postgresql` Helm chart 15.x, `pg_basebackup`, MinIO `mc`, Kubernetes 1.29+

**File locations:**
- `helm/charts/postgresql/Chart.yaml` — wrapper chart
- `helm/charts/postgresql/values.yaml` — primary configuration
- `helm/charts/postgresql/values-prod.yaml` — production overrides
- `k8s/postgres/backup-cronjob.yaml` — nightly backup CronJob
- `k8s/postgres/backup-minio-policy.json` — MinIO 30-day lifecycle
- `k8s/postgres/pdb.yaml` — PodDisruptionBudget
- `argocd/apps/services/postgresql.yaml`

---

### Helm wrapper chart

```yaml
# helm/charts/postgresql/Chart.yaml
apiVersion: v2
name:        postgresql
description: PostgreSQL 15 for ContextIQ (Bitnami chart wrapper)
type:        application
version:     0.1.0
dependencies:
  - name:       postgresql
    version:    "15.5.x"      # pin minor — Bitnami chart version tracking pg 15
    repository: https://charts.bitnami.com/bitnami
```

```yaml
# helm/charts/postgresql/values.yaml
postgresql:
  image:
    tag: "15.7.0-debian-12-r0"    # pin exact image tag for reproducibility

  auth:
    # Credentials managed by Vault Agent Injector (TASK-US047-02/03)
    # The chart's built-in secret is disabled; password sourced from /vault/secrets/postgres.env
    existingSecret:         ""
    secretKeys:
      adminPasswordKey:     ""
    postgresPassword:       ""   # intentionally empty — Vault provides it at runtime
    username:               "contextiq_app"
    database:               "contextiq"

  primary:
    # AC-1: encrypted PVC (TASK-US048-04)
    persistence:
      enabled:          true
      storageClass:     contextiq-encrypted-gp3
      size:             100Gi

    # AC-5 dependency: PostgreSQL tuning for max 200 connections (tuned in TASK-US050-04)
    configuration: |
      max_connections = 250        # headroom above PgBouncer's 200 limit
      shared_buffers  = 2GB        # ~25% of node RAM (8 GB node assumed)
      effective_cache_size = 6GB
      wal_level       = replica    # required for streaming replication (AC-6)
      max_wal_senders = 5          # support up to 2 replicas + 1 backup slot + 2 spare
      wal_keep_size   = 512MB
      hot_standby     = on

    resources:
      requests: { cpu: "1",    memory: "4Gi" }
      limits:   { cpu: "4",    memory: "8Gi" }

    # Vault Agent sidecar injection (TASK-US047-03 pattern)
    podAnnotations:
      vault.hashicorp.com/agent-inject:                  "true"
      vault.hashicorp.com/role:                          "postgres-admin"
      vault.hashicorp.com/agent-inject-secret-postgres:  "secret/data/contextiq/postgres/admin"
      vault.hashicorp.com/agent-inject-template-postgres: |
        {{- with secret "secret/data/contextiq/postgres/admin" }}
        export POSTGRESQL_POSTGRES_PASSWORD="{{ .Data.data.password }}"
        {{- end }}

    initdb:
      scripts:
        # Create app-level role with limited privileges at first boot
        init_roles.sql: |
          CREATE ROLE contextiq_app WITH LOGIN;
          GRANT CONNECT ON DATABASE contextiq TO contextiq_app;
          GRANT USAGE  ON SCHEMA public TO contextiq_app;
          ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO contextiq_app;

  # Read replicas configured separately in TASK-US050-05
  readReplicas:
    replicaCount: 0    # enabled in values-prod.yaml (AC-6)

  metrics:
    enabled: true        # Prometheus postgres_exporter sidecar
    serviceMonitor:
      enabled:   true
      namespace: contextiq-observability
```

```yaml
# helm/charts/postgresql/values-prod.yaml
postgresql:
  primary:
    resources:
      requests: { cpu: "2",    memory: "8Gi" }
      limits:   { cpu: "8",    memory: "16Gi" }
    persistence:
      size: 500Gi

  readReplicas:
    replicaCount: 2    # AC-6: 2 replicas for reporting (enabled in prod)
```

---

### Nightly backup CronJob

```yaml
# k8s/postgres/backup-cronjob.yaml
# AC-1: Daily backup at 01:00 UTC using pg_basebackup, archived to MinIO.
apiVersion: batch/v1
kind: CronJob
metadata:
  name: postgres-backup
  namespace: contextiq-data
spec:
  schedule:          "0 1 * * *"    # 01:00 UTC daily
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit:     3
  jobTemplate:
    spec:
      backoffLimit: 2
      template:
        metadata:
          annotations:
            # Vault Agent provides MinIO credentials at runtime
            vault.hashicorp.com/agent-inject:                    "true"
            vault.hashicorp.com/role:                            "postgres-backup"
            vault.hashicorp.com/agent-inject-secret-minio:       "secret/data/contextiq/minio/backup"
            vault.hashicorp.com/agent-inject-template-minio: |
              {{- with secret "secret/data/contextiq/minio/backup" }}
              export MINIO_ACCESS_KEY="{{ .Data.data.access_key }}"
              export MINIO_SECRET_KEY="{{ .Data.data.secret_key }}"
              {{- end }}
            vault.hashicorp.com/agent-inject-secret-postgres:    "secret/data/contextiq/postgres/admin"
            vault.hashicorp.com/agent-inject-template-postgres: |
              {{- with secret "secret/data/contextiq/postgres/admin" }}
              export PGPASSWORD="{{ .Data.data.password }}"
              {{- end }}
        spec:
          restartPolicy: OnFailure
          serviceAccountName: postgres-backup
          containers:
            - name: backup
              image: bitnami/postgresql:15.7.0-debian-12-r0
              command: ["/bin/bash", "-c"]
              args:
                - |
                  set -euo pipefail
                  # Source Vault-injected credentials
                  . /vault/secrets/postgres.env
                  . /vault/secrets/minio.env

                  TIMESTAMP=$(date +%Y%m%d-%H%M%S)
                  BACKUP_FILE="/tmp/pg_backup_${TIMESTAMP}.tar.gz"

                  echo "=== Starting PostgreSQL backup: $TIMESTAMP ==="
                  pg_basebackup \
                    -h postgresql.contextiq-data.svc.cluster.local \
                    -U postgres \
                    -D /tmp/pgbackup_${TIMESTAMP} \
                    -Ft -z -Xs -P \
                    --checkpoint=fast

                  tar -czf "$BACKUP_FILE" -C /tmp "pgbackup_${TIMESTAMP}"

                  echo "=== Uploading to MinIO ==="
                  mc alias set minio \
                    http://minio.contextiq-infra.svc.cluster.local:9000 \
                    "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"
                  mc cp "$BACKUP_FILE" "minio/contextiq-postgres-backups/daily/${TIMESTAMP}.tar.gz"

                  echo "=== Backup complete: daily/${TIMESTAMP}.tar.gz ==="
                  rm -rf "$BACKUP_FILE" "/tmp/pgbackup_${TIMESTAMP}"
              resources:
                requests: { cpu: "500m", memory: "512Mi" }
                limits:   { cpu: "2",    memory: "1Gi" }
```

---

### MinIO 30-day lifecycle policy for backup bucket

```json
// k8s/postgres/backup-minio-policy.json
// AC-1: 30-day retention — objects expire after 30 days automatically.
{
  "Rules": [
    {
      "ID": "postgres-backup-30d-retention",
      "Status": "Enabled",
      "Filter": { "Prefix": "daily/" },
      "Expiration": { "Days": 30 }
    },
    {
      "ID": "postgres-backup-weekly-180d",
      "Status": "Enabled",
      "Filter": { "Prefix": "weekly/" },
      "Expiration": { "Days": 180 }
    }
  ]
}
```

Apply with:
```bash
mc ilm import minio/contextiq-postgres-backups < k8s/postgres/backup-minio-policy.json
```

---

### PodDisruptionBudget

```yaml
# k8s/postgres/pdb.yaml
# AC-5 dependency: guarantees at least 1 primary always available during voluntary disruptions.
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: postgresql-primary-pdb
  namespace: contextiq-data
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name:      postgresql
      app.kubernetes.io/component: primary
  minAvailable: 1
```

---

### ArgoCD Application

```yaml
# argocd/apps/services/postgresql.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: postgresql
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://charts.bitnami.com/bitnami
    chart:          postgresql
    targetRevision: "15.5.x"
    helm:
      valueFiles:
        - values.yaml
        - values-prod.yaml
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-data
  syncPolicy:
    automated: { prune: false, selfHeal: true }
    # prune: false — StatefulSet PVCs must not be auto-deleted
```

## Acceptance Criteria

- [ ] `kubectl get statefulset postgresql-primary -n contextiq-data` shows `READY 1/1` (AC-1)
- [ ] PVC `data-postgresql-primary-0` is bound and uses `contextiq-encrypted-gp3` StorageClass (AC-1, TASK-US048-04)
- [ ] Backup CronJob fires at 01:00 UTC; `mc ls minio/contextiq-postgres-backups/daily/` shows an object dated today (AC-1)
- [ ] `mc ilm ls minio/contextiq-postgres-backups` shows the 30-day expiry rule active (AC-1)
- [ ] `psql -c "SHOW wal_level;"` returns `replica` — replication pre-configured (AC-6 prerequisite)
- [ ] `kubectl get pdb postgresql-primary-pdb -n contextiq-data` shows `ALLOWED-DISRUPTIONS: 0` when 1 pod is running (AC-5 prerequisite)

## Dependencies

- TASK-US045-01 — `contextiq-data` namespace must exist
- TASK-US047-02 — Vault secrets at `secret/contextiq/postgres/admin` and `secret/contextiq/minio/backup`
- TASK-US047-03 — Vault Agent Injector must be running for sidecar credential injection
- TASK-US048-04 — `contextiq-encrypted-gp3` StorageClass must exist

## Definition of Done

- [ ] `helm install postgresql bitnami/postgresql -n contextiq-data -f values.yaml -f values-prod.yaml` completes
- [ ] `psql "host=postgresql.contextiq-data.svc.cluster.local dbname=contextiq"` connects (via Vault dynamic credentials)
- [ ] Backup CronJob completes successfully in staging; backup object visible in MinIO
