"""
AC-3: MinIO archival tests using moto.

Verifies that AuditArchiveService.archive_day() uploads a correctly-keyed
gzip NDJSON object to S3/MinIO and skips the upload when there are no rows.

Requires: moto[s3]>=5.0 (supports aiobotocore via botocore-level patching).
"""
from __future__ import annotations

import gzip
import json
from datetime import date

import boto3
import pytest
from moto import mock_aws
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.admin_audit_log.archive_service import AuditArchiveService
from src.audit.admin_audit_log.archive_settings import ArchiveSettings


@pytest.fixture
def archive_settings() -> ArchiveSettings:
    return ArchiveSettings(
        minio_endpoint="http://localhost:5555",   # intercepted by moto
        minio_bucket="contextiq-audit-archive",
        minio_access_key="test",
        minio_secret_key="test",
        minio_region="us-east-1",
    )


@mock_aws
@pytest.mark.asyncio
async def test_archive_uploads_correct_key(
    db_session: AsyncSession,
    seed_audit_rows_yesterday,
    archive_settings: ArchiveSettings,
) -> None:
    """AC-3: archive_day uploads to audit-log/{YYYY}/{MM}/{DD}.ndjson.gz."""
    # Pre-create bucket in moto
    boto3.client("s3", region_name="us-east-1").create_bucket(
        Bucket=archive_settings.minio_bucket
    )

    service = AuditArchiveService(archive_settings)
    day     = date(2026, 7, 9)   # matches seed_audit_rows_yesterday timestamps
    count   = await service.archive_day(db_session, day=day)

    assert count > 0

    s3  = boto3.client("s3", region_name="us-east-1")
    obj = s3.get_object(
        Bucket=archive_settings.minio_bucket,
        Key="audit-log/2026/07/09.ndjson.gz",
    )
    body  = obj["Body"].read()
    lines = gzip.decompress(body).decode("utf-8").strip().splitlines()
    rows  = [json.loads(line) for line in lines]

    assert len(rows) == count
    assert all("row_hash" in row for row in rows)   # AC-6 hash included in archive


@mock_aws
@pytest.mark.asyncio
async def test_archive_no_rows_skips_upload(
    db_session: AsyncSession,
    archive_settings: ArchiveSettings,
) -> None:
    """AC-3: If no rows exist for the target day, no object is uploaded."""
    boto3.client("s3", region_name="us-east-1").create_bucket(
        Bucket=archive_settings.minio_bucket
    )

    service = AuditArchiveService(archive_settings)
    count   = await service.archive_day(db_session, day=date(2020, 1, 1))
    assert count == 0

    s3 = boto3.client("s3", region_name="us-east-1")
    objects = s3.list_objects_v2(Bucket=archive_settings.minio_bucket)
    assert objects.get("KeyCount", 0) == 0
