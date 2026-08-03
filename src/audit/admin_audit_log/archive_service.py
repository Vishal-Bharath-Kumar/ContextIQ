"""
AuditArchiveService — daily MinIO archival of admin_audit_log rows.

AC-3: exports yesterday's rows as gzip-compressed NDJSON to
      `contextiq-audit-archive/audit-log/{YYYY}/{MM}/{DD}.ndjson.gz`
      once per day (invoked by a Kubernetes CronJob at 02:00 UTC).
AC-6: each archived row includes `row_hash` so the hash chain can be
      independently verified from the archive.
OWASP A02: objects are encrypted at rest using AES-256 SSE.
"""
from __future__ import annotations

import gzip
import io
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiobotocore.session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.admin_audit_log.archive_settings import ArchiveSettings
from src.audit.admin_audit_log.models import AdminAuditLog

logger = logging.getLogger(__name__)

# Rows fetched per DB page — caps per-query result-set size in memory.
_CHUNK_SIZE = 1_000


class AuditArchiveService:
    """
    AC-3: Exports one calendar day's admin_audit_log rows to MinIO.

    Object key: ``audit-log/{YYYY}/{MM}/{DD}.ndjson.gz``

    All rows for the target day are compressed in memory then written with a
    single ``put_object`` call.  At Phase 2 scale (< 100 k rows/day,
    typically < 50 MB uncompressed) this is well within the 512 MiB pod
    memory limit.  If daily volumes grow to millions of rows, switch to the
    multipart upload API instead.
    """

    def __init__(self, settings: ArchiveSettings | None = None) -> None:
        self._settings = settings or ArchiveSettings()

    async def archive_day(self, session: AsyncSession, day: date | None = None) -> int:
        """
        Archive one calendar day.

        Parameters
        ----------
        session:
            Active ``AsyncSession`` for PostgreSQL queries.
        day:
            Target day (UTC).  Defaults to yesterday.

        Returns
        -------
        int
            Number of rows archived.
        """
        target_day = day or (datetime.now(timezone.utc).date() - timedelta(days=1))
        rows = await self._fetch_rows(session, target_day)

        if not rows:
            logger.info("audit_archive: no rows for %s — skipping upload", target_day)
            return 0

        object_key = self._object_key(target_day)
        compressed = self._compress_ndjson(rows)
        await self._upload(object_key, compressed)
        logger.info(
            "audit_archive: uploaded %d rows for %s → %s",
            len(rows),
            target_day,
            object_key,
        )
        return len(rows)

    async def _fetch_rows(
        self,
        session: AsyncSession,
        day: date,
    ) -> list[dict[str, Any]]:
        """
        Fetch all admin_audit_log rows whose timestamp falls within ``day`` (UTC).

        Uses OFFSET pagination with ``_CHUNK_SIZE`` rows per query to avoid
        loading an unbounded result set into memory in a single query.
        """
        start = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(day.year, day.month, day.day, 23, 59, 59, 999_999, tzinfo=timezone.utc)

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
                    "row_hash":      row.row_hash,   # AC-6: preserved for chain verification
                })
            offset += _CHUNK_SIZE
            if len(batch) < _CHUNK_SIZE:
                break

        return rows

    @staticmethod
    def _compress_ndjson(rows: list[dict[str, Any]]) -> bytes:
        """Serialise rows as NDJSON (one JSON object per line) and gzip-compress."""
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
            for row in rows:
                line = json.dumps(row, separators=(",", ":")) + "\n"
                gz.write(line.encode("utf-8"))
        return buf.getvalue()

    @staticmethod
    def _object_key(day: date) -> str:
        """Return the MinIO object key for the given day."""
        return f"audit-log/{day.year:04d}/{day.month:02d}/{day.day:02d}.ndjson.gz"

    async def _upload(self, object_key: str, data: bytes) -> None:
        """Upload ``data`` to MinIO using the S3-compatible API."""
        s = self._settings
        aioboto_session = aiobotocore.session.get_session()
        async with aioboto_session.create_client(
            "s3",
            endpoint_url=s.minio_endpoint,
            aws_access_key_id=s.minio_access_key,
            aws_secret_access_key=s.minio_secret_key,
            region_name=s.minio_region,
        ) as client:
            await client.put_object(
                Bucket=s.minio_bucket,
                Key=object_key,
                Body=data,
                ContentType="application/x-ndjson",
                ContentEncoding="gzip",
                # AC-A02: encrypt audit objects at rest with AES-256 SSE
                ServerSideEncryption="AES256",
            )
