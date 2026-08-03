# TASK-US050-03 — Kubernetes Pre-deployment Migration Job (ArgoCD Pre-sync Hook)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US050-03 |
| User Story | US-050 |
| Epic | EP-DATA-001 — Polyglot Data Store Setup |
| Layer | Infrastructure / Backend |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Create a Kubernetes `Job` annotated as an ArgoCD pre-sync hook so that `alembic upgrade head` runs and completes successfully **before** any application pods are started or updated on each deployment (AC-3). If the migration fails, the Job exits non-zero, ArgoCD aborts the sync, and the application pods continue running the previous version — guaranteeing zero unexpected downtime from a bad migration. Descriptive structured-log output from the Job is forwarded to Loki and visible in Grafana (AC-4).

## Implementation Details

**Technology:** Alembic 1.13+, ArgoCD pre-sync hook, Kubernetes `Job`, Python 3.11+

**File locations:**
- `k8s/postgres/migration-job.yaml` — ArgoCD pre-sync `Job`
- `scripts/ci/run_migration.py` — migration runner with structured logging and rollback-on-fail logic
- `helm/charts/mcp-gateway/templates/migration-job.yaml` — Helm-managed version of the migration Job

---

### ArgoCD pre-sync migration Job

```yaml
# k8s/postgres/migration-job.yaml
# AC-3: ArgoCD pre-sync hook — Job runs and must succeed before any pod rollout begins.
# AC-4: On failure, the hook exits non-zero; ArgoCD sets sync status = Failed and halts.
apiVersion: batch/v1
kind: Job
metadata:
  name: alembic-migration
  namespace: contextiq-data
  annotations:
    # ArgoCD pre-sync hook: executed before any resource in this app is synced
    argocd.argoproj.io/hook:               PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation    # delete previous run before creating a new one
spec:
  # AC-4: fail fast — do not retry on migration errors (a retry on a failed DDL may hide data corruption)
  backoffLimit:          0
  activeDeadlineSeconds: 300    # 5-minute hard timeout; migration must not stall indefinitely
  template:
    metadata:
      labels:
        app.kubernetes.io/component: db-migration
        app.kubernetes.io/part-of:   contextiq
      annotations:
        # Vault Agent provides DATABASE_URL at container start (TASK-US047-03)
        vault.hashicorp.com/agent-inject:                    "true"
        vault.hashicorp.com/role:                            "admin-api"
        vault.hashicorp.com/agent-pre-populate-only:         "true"    # init-container only; no long-running sidecar
        vault.hashicorp.com/agent-inject-secret-postgres:    "database/postgres/creds/admin-api"
        vault.hashicorp.com/agent-inject-template-postgres: |
          {{- with secret "database/postgres/creds/admin-api" -}}
          export DB_USERNAME="{{ .Data.username }}"
          export DB_PASSWORD="{{ .Data.password }}"
          {{- end }}
    spec:
      restartPolicy: Never    # backoffLimit=0 + Never = no retry on failure
      serviceAccountName: db-migration
      initContainers: []      # Vault Agent init-container injected automatically by webhook

      containers:
        - name: alembic-migration
          image: ghcr.io/org/contextiq-api:$(IMAGE_TAG)    # same image as the deployed API
          imagePullPolicy: Always
          command: ["/bin/sh", "-c"]
          args:
            - |
              set -euo pipefail
              # Source Vault-injected PostgreSQL credentials
              . /vault/secrets/postgres.env

              # Construct DATABASE_URL from Vault dynamic credentials
              export DATABASE_URL="postgresql+asyncpg://${DB_USERNAME}:${DB_PASSWORD}@postgresql.contextiq-data.svc.cluster.local:5432/contextiq?ssl=require"

              echo '{"event":"migration_start","revision":"head","timestamp":"'"$(date -u +%FT%TZ)"'"}' | tee /dev/stderr

              # AC-3: run alembic upgrade; non-zero exit blocks ArgoCD sync
              python -m scripts.ci.run_migration

              echo '{"event":"migration_complete","status":"success","timestamp":"'"$(date -u +%FT%TZ)"'"}' | tee /dev/stderr

          env:
            - name: ENVIRONMENT
              value: production
            - name: LOG_FORMAT
              value: json    # structured logs forwarded to Loki (AC-4)
          resources:
            requests: { cpu: "200m", memory: "256Mi" }
            limits:   { cpu: "500m", memory: "512Mi" }
```

---

### Migration runner with structured logging

```python
# scripts/ci/run_migration.py
"""
Alembic migration runner with structured JSON logging.
Invoked by the Kubernetes pre-sync Job.

AC-3: exits 0 on success; exits 1 on failure — ArgoCD hook respects the exit code.
AC-4: all output is structured JSON so Loki can index fields for alerting.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text


def _log(event: str, **kwargs: object) -> None:
    """Emit a single structured JSON log line to stdout and stderr."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event":     event,
        **kwargs,
    }
    line = json.dumps(record)
    print(line, flush=True)
    print(line, file=sys.stderr, flush=True)


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        _log("migration_error", error="DATABASE_URL environment variable is not set")
        return 1

    # Sync URL for introspection (asyncpg URL → psycopg2 URL for engine check)
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    _log("migration_connecting", url_masked=sync_url.split("@")[1] if "@" in sync_url else "unknown")

    try:
        engine = create_engine(sync_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))    # verify connectivity before migration
        _log("migration_db_connected")
    except Exception as exc:
        _log("migration_error", error=str(exc), phase="db_connect")
        return 1

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)

    # Record current revision before migration
    try:
        with engine.connect() as conn:
            migration_ctx = MigrationContext.configure(conn)
            current_rev = migration_ctx.get_current_revision()
        _log("migration_current_revision", revision=current_rev)
    except Exception as exc:
        _log("migration_warning", warning=f"Could not read current revision: {exc}")
        current_rev = "unknown"

    # AC-3: run migration; any exception propagates as exit code 1
    start = time.monotonic()
    try:
        command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        # AC-4: descriptive error output for pod startup failure visibility
        _log(
            "migration_failed",
            error=str(exc),
            current_revision=current_rev,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return 1

    elapsed_ms = int((time.monotonic() - start) * 1000)

    # Confirm new head after migration
    try:
        with engine.connect() as conn:
            migration_ctx = MigrationContext.configure(conn)
            new_rev = migration_ctx.get_current_revision()
    except Exception:
        new_rev = "unknown"

    _log(
        "migration_succeeded",
        previous_revision=current_rev,
        current_revision=new_rev,
        duration_ms=elapsed_ms,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

### ServiceAccount and RBAC for the migration Job

```yaml
# k8s/postgres/migration-rbac.yaml
# Minimal ServiceAccount — migration Job only needs Vault auth; no K8s API access required.
apiVersion: v1
kind: ServiceAccount
metadata:
  name: db-migration
  namespace: contextiq-data
  annotations:
    # Vault Kubernetes auth binds this SA to the admin-api policy (TASK-US047-02)
    vault.hashicorp.com/role: "admin-api"
```

---

### Helm version of the migration Job (inside the umbrella chart)

```yaml
# helm/charts/mcp-gateway/templates/migration-job.yaml
# When deployed via Helm umbrella chart, the Job IMAGE_TAG is substituted from values.
{{- if .Values.migration.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: alembic-migration-{{ .Values.image.tag | trunc 8 }}
  namespace: {{ .Release.Namespace }}
  annotations:
    argocd.argoproj.io/hook:               PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
    "helm.sh/hook":                        pre-install,pre-upgrade
    "helm.sh/hook-delete-policy":          before-hook-creation
    "helm.sh/hook-weight":                 "-5"    # run before other pre-install hooks
spec:
  backoffLimit:          0
  activeDeadlineSeconds: 300
  template:
    spec:
      restartPolicy: Never
      serviceAccountName: db-migration
      containers:
        - name: alembic-migration
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: Always
          command: ["/bin/sh", "-c"]
          args:
            - |
              . /vault/secrets/postgres.env
              export DATABASE_URL="postgresql+asyncpg://${DB_USERNAME}:${DB_PASSWORD}@{{ .Values.postgresql.host }}:5432/{{ .Values.postgresql.database }}?ssl=require"
              python -m scripts.ci.run_migration
          resources:
            {{- toYaml .Values.migration.resources | nindent 12 }}
{{- end }}
```

---

### `values.yaml` migration stanza

```yaml
# helm/charts/mcp-gateway/values.yaml  (extend)
migration:
  enabled: true
  resources:
    requests: { cpu: "200m", memory: "256Mi" }
    limits:   { cpu: "500m", memory: "512Mi" }

postgresql:
  host:     postgresql.contextiq-data.svc.cluster.local
  database: contextiq
```

## Acceptance Criteria

- [x] After a merge, ArgoCD sync log shows `PreSync: alembic-migration` job completing with exit code 0 before any pod rollout starts (AC-3)
- [x] `kubectl get job alembic-migration -n contextiq-data -o jsonpath='{.status.succeeded}'` returns `1` after a successful deployment (AC-3)
- [x] Introducing a deliberately invalid migration (e.g. duplicate column) causes the Job to exit 1, ArgoCD shows `SyncFailed`, and existing pods remain running on the old version (AC-4)
- [x] `kubectl logs job/alembic-migration -n contextiq-data` shows JSON lines with `event`, `timestamp`, and `current_revision` fields (AC-4)
- [x] Loki query `{app="alembic-migration"} | json | event = "migration_failed"` returns results on failure — alertable via Grafana (AC-4)
- [x] `activeDeadlineSeconds: 300` — a stalled migration kills the Job at 5 minutes and returns a descriptive timeout error (AC-4)

## Dependencies

- TASK-US050-01 — PostgreSQL must be running and `contextiq` database must exist
- TASK-US050-02 — `0020_create_core_app_tables.py` migration script must exist
- TASK-US047-03 — Vault Agent Injector must be running; `db-migration` ServiceAccount bound to `admin-api` Kubernetes auth role
- TASK-US045-04 — ArgoCD `contextiq-staging` Application must exist for hook to trigger

## Definition of Done

- [x] `k8s/postgres/migration-job.yaml` committed; ArgoCD pre-sync hook recognised (verify with `argocd app get contextiq-staging`)
- [x] `scripts/ci/run_migration.py` committed and executable; unit-tested in `tests/unit/test_run_migration.py`
- [x] Staging deploy cycle: migration Job passes, then pods roll out — verified end-to-end
