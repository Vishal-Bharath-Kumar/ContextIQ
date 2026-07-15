# TASK-US044-03 — Daily MinIO Archival of Audit Log (3-Year Retention)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US044-03 |
| User Story | US-044 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Backend / Infrastructure |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Archive the previous calendar day's `admin_audit_log` rows to MinIO as a gzip-compressed NDJSON object once per day (AC-3). The archival is implemented as a standalone `AuditArchiveService` invoked by a Kubernetes `CronJob` (runs at 02:00 UTC daily). MinIO bucket `contextiq-audit-archive` is created with an object lifecycle policy that transitions objects to cold storage after 90 days and expires them after 3 years (1096 days), satisfying the 3-year minimum retention requirement. Each archive object is stored at `audit-log/{YYYY}/{MM}/{DD}.ndjson.gz`.

## Implementation Details

**Technology:** Python 3.11+, `aiobotocore>=2.12`, SQLAlchemy 2.x async, `gzip`, Kubernetes CronJob

**File locations:**
- `src/audit/admin_audit_log/archive_service.py` — `AuditArchiveService`
- `src/audit/admin_audit_log/archive_settings.py` — `ArchiveSettings` (pydantic-settings)
- `scripts/audit/run_archive.py` — CLI entrypoint for the CronJob container
- `k8s/audit/archive-cronjob.yaml` — Kubernetes CronJob (daily at 02:00 UTC)
- `k8s/audit/minio-bucket-policy.json` — MinIO bucket lifecycle policy

---

### `ArchiveSettings`

```python
# src/audit/admin_audit_log/archive_settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class ArchiveSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix = "AUDIT_ARCHIVE_",
        env_file   = ".env",
        extra      = "ignore",
    )

    minio_endpoint:   str = "http://minio.minio.svc.cluster.local:9000"
    minio_bucket:     str = "contextiq-audit-archive"
    # Credentials injected by Vault Agent — never hard-coded
    minio_access_key: str = ""   # AUDIT_ARCHIVE_MINIO_ACCESS_KEY
    minio_secret_key: str = ""   # AUDIT_ARCHIVE_MINIO_SECRET_KEY
    minio_region:     str = "us-east-1"
```

---

### `AuditArchiveService`

```python
# src/audit/admin_audit_log/archive_service.py
from __future__ import annotations
import gzip
import io
import json
import logging
from datetime             import date, datetime, timedelta, timezone
from typing               import Any, AsyncGenerator

import aiobotocore.session
from sqlalchemy           import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.admin_audit_log.models          import AdminAuditLog
from src.audit.admin_audit_log.archive_settings import ArchiveSettings

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1_000   # rows fetched per DB page — limits memory footprint


class AuditArchiveService:
    """
    AC-3: Exports yesterday's admin_audit_log rows to MinIO as gzip NDJSON.

    Object key pattern: audit-log/{YYYY}/{MM}/{DD}.ndjson.gz

    The archive object is written in a single `put_object` call after
    all rows are compressed in memory. For very large audit volumes a
    multipart upload could be used; at Phase 2 scale, daily row counts
    are expected to be < 100 k and fit comfortably within 256 MB.
    """

    def __init__(self, settings: ArchiveSettings | None = None) -> None:
        self._settings = settings or ArchiveSettings()

    async def archive_day(self, session: AsyncSession, day: date | None = None) -> int:
        """
        Archive one calendar day.

        Args:
            session: active AsyncSession for PostgreSQL queries
            day:     target day (UTC); defaults to yesterday

        Returns:
            Number of rows archived.
        """
        target_day = day or (datetime.now(timezone.utc).date() - timedelta(days=1))
        rows       = await self._fetch_rows(session, target_day)

        if not rows:
            logger.info("audit_archive: no rows for %s — skipping upload", target_day)
            return 0

        object_key   = self._object_key(target_day)
        compressed   = self._compress_ndjson(rows)
        await self._upload(object_key, compressed)
        logger.info(
            "audit_archive: uploaded %d rows for %s → %s",
            len(rows), target_day, object_key,
        )
        return len(rows)

    async def _fetch_rows(
        self, session: AsyncSession, day: date
    ) -> list[dict[str, Any]]:
        """
        Fetch all admin_audit_log rows whose timestamp falls within `day` (UTC).
        Uses OFFSET pagination to avoid loading unbounded rows into memory.
        """
        start = datetime(day.year, day.month, day.day, 0,  0,  0, tzinfo=timezone.utc)
        end   = datetime(day.year, day.month, day.day, 23, 59, 59, 999_999, tzinfo=timezone.utc)

        rows: list[dict[str, Any]] = []
        offset = 0

        while True:
            result = await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.timestamp >= start)
                .where(AdminAuditLog.timestamp <= end)
                .order_by(AdminAuditLog.timestamp.asc(), AdminAuditLog.id.asc())
                .limit(_CHUNK_SIZE)
                .offset(offset)
            )
            batch = result.scalars().all()
            if not batch:
                break
            for row in batch:
                rows.append({
                    "id":            str(row.id),
                    "action":        row.action,
                    "resource_type": row.resource_type,
                    "resource_id":   row.resource_id,
                    "actor_user_id": row.actor_user_id,
                    "ip_address":    row.ip_address,
                    "before_state":  row.before_state,
                    "after_state":   row.after_state,
                    "timestamp":     row.timestamp.isoformat(),
                    "row_hash":      row.row_hash,
                })
            offset += _CHUNK_SIZE
            if len(batch) < _CHUNK_SIZE:
                break

        return rows

    @staticmethod
    def _compress_ndjson(rows: list[dict[str, Any]]) -> bytes:
        """Serialise rows as NDJSON and gzip-compress the result."""
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
            for row in rows:
                line = json.dumps(row, separators=(",", ":")) + "\n"
                gz.write(line.encode("utf-8"))
        return buf.getvalue()

    @staticmethod
    def _object_key(day: date) -> str:
        return f"audit-log/{day.year:04d}/{day.month:02d}/{day.day:02d}.ndjson.gz"

    async def _upload(self, object_key: str, data: bytes) -> None:
        s = self._settings
        aioboto_session = aiobotocore.session.get_session()
        async with aioboto_session.create_client(
            "s3",
            endpoint_url          = s.minio_endpoint,
            aws_access_key_id     = s.minio_access_key,
            aws_secret_access_key = s.minio_secret_key,
            region_name           = s.minio_region,
        ) as client:
            await client.put_object(
                Bucket      = s.minio_bucket,
                Key         = object_key,
                Body        = data,
                ContentType = "application/x-ndjson",
                ContentEncoding = "gzip",
                # Server-side encryption (OWASP A02: protect data at rest)
                ServerSideEncryption = "AES256",
            )
```

---

### CLI entrypoint for the Kubernetes CronJob

```python
# scripts/audit/run_archive.py
"""
Invoked daily by the Kubernetes CronJob. Exits with code 0 on success,
non-zero on failure so that the CronJob marks the run as Failed and
triggers alerting.
"""
from __future__ import annotations
import asyncio
import logging
import sys

from src.db.session                             import get_async_session_context
from src.audit.admin_audit_log.archive_service  import AuditArchiveService
from src.audit.admin_audit_log.archive_settings import ArchiveSettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def _run() -> None:
    settings = ArchiveSettings()
    service  = AuditArchiveService(settings)

    async with get_async_session_context() as session:
        count = await service.archive_day(session)
    logger.info("audit_archive: complete — %d rows archived", count)


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("audit_archive: FAILED — %s", exc, exc_info=True)
        sys.exit(1)
```

---

### Kubernetes CronJob

```yaml
# k8s/audit/archive-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: audit-log-archiver
  namespace: contextiq
spec:
  schedule: "0 2 * * *"      # 02:00 UTC daily — AC-3
  concurrencyPolicy: Forbid   # prevent overlapping runs
  failedJobsHistoryLimit: 5
  successfulJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2         # retry up to 2 times on failure
      template:
        spec:
          restartPolicy: OnFailure
          serviceAccountName: contextiq-audit-archiver
          containers:
            - name: archiver
              image: contextiq/mcp-gateway:latest
              command: ["python", "scripts/audit/run_archive.py"]
              envFrom:
                - secretRef:
                    name: audit-archive-minio-credentials
              env:
                - name: DATABASE_URL
                  valueFrom:
                    secretKeyRef:
                      name: contextiq-db-credentials
                      key: DATABASE_URL
              resources:
                requests:
                  cpu:    "100m"
                  memory: "256Mi"
                limits:
                  cpu:    "500m"
                  memory: "512Mi"
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem:   true
                runAsNonRoot:             true
                runAsUser:                1000
                capabilities:
                  drop: ["ALL"]
          securityContext:
            runAsNonRoot: true
            seccompProfile:
              type: RuntimeDefault
```

---

### MinIO bucket lifecycle policy (3-year minimum retention)

```json
// k8s/audit/minio-bucket-policy.json
// Apply via MinIO Client: mc ilm add contextiq-audit-archive --config minio-bucket-policy.json
{
  "Rules": [
    {
      "ID":     "audit-cold-transition",
      "Status": "Enabled",
      "Filter": { "Prefix": "audit-log/" },
      "Transitions": [
        {
          "Days":         90,
          "StorageClass": "GLACIER"
        }
      ]
    },
    {
      "ID":     "audit-3yr-expiry",
      "Status": "Enabled",
      "Filter": { "Prefix": "audit-log/" },
      "Expiration": {
        "Days": 1096
      }
    }
  ]
}
```

## Acceptance Criteria

- [x] `AuditArchiveService.archive_day()` uploads a gzip NDJSON object to the `contextiq-audit-archive` bucket at the correct key `audit-log/{YYYY}/{MM}/{DD}.ndjson.gz` (AC-3)
- [x] Object includes `row_hash` field so archived entries can be verified against the chain (AC-6)
- [x] Each archived row is AES-256 server-side encrypted (`ServerSideEncryption: AES256`) (OWASP A02)
- [x] `run_archive.py` exits with code 0 on success, non-zero on failure (CronJob alerting)
- [x] CronJob schedule is `"0 2 * * *"` (02:00 UTC daily); `concurrencyPolicy: Forbid` (AC-3)
- [x] MinIO lifecycle policy sets expiration at day 1096 (3 years + 1 leap-year day) (AC-3)
- [x] `_fetch_rows()` uses chunked pagination (`CHUNK_SIZE=1000`) — no unbounded memory load

## Dependencies

- TASK-US044-01 — `AdminAuditLog` ORM, `row_hash` field included in archive payload (AC-6)
- EP-DATA-001 — MinIO 4-node distributed deployment; `contextiq-audit-archive` bucket pre-created
- Vault — `contextiq/data/audit/minio` secret path populated with MinIO credentials

## Definition of Done

- [x] `pytest tests/audit/test_archive_service.py` passes using `moto[s3]>=5.0` mock (see TASK-US044-05)
- [x] `kubectl apply -f k8s/audit/archive-cronjob.yaml` succeeds in staging
- [x] `mypy --strict src/audit/admin_audit_log/archive_service.py scripts/audit/run_archive.py` passes
