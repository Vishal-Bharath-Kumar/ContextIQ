"""MinIO/S3-compatible adapter for immutable execution trace storage — TASK-US034-02.

Implements write-once semantics via bucket versioning (AC-3) and applies a
lifecycle expiry policy for 90-day minimum retention (AC-5).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiobotocore.session
from botocore.exceptions import ClientError
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.audit.trace.schemas import ExecutionTrace

logger = logging.getLogger(__name__)

_CONTENT_TYPE = "application/json"


class TraceObjectStoreSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACE_STORE_",
        env_file=".env",
        extra="ignore",
    )

    endpoint_url: str = "http://minio:9000"
    bucket: str = "contextiq-traces"
    aws_access_key_id: str = "minioadmin"
    aws_secret_access_key: str = "minioadmin"  # noqa: S105
    region_name: str = "us-east-1"
    server_side_encryption: str | None = None

    # AC-5: retention window (days); minimum 90, default 365
    retention_days: int = 365
    retention_days_min: int = 90  # validated in __init__; never configurable below 90

    def model_post_init(self, __context: object) -> None:
        self.endpoint_url = _coalesce_legacy_env(
            current=self.endpoint_url,
            default="http://minio:9000",
            legacy_env="AUDIT_ARCHIVE_MINIO_ENDPOINT",
        )
        self.aws_access_key_id = _coalesce_legacy_env(
            current=self.aws_access_key_id,
            default="minioadmin",
            legacy_env="AUDIT_ARCHIVE_MINIO_ACCESS_KEY",
        )
        self.aws_secret_access_key = _coalesce_legacy_env(
            current=self.aws_secret_access_key,
            default="minioadmin",
            legacy_env="AUDIT_ARCHIVE_MINIO_SECRET_KEY",
        )
        self.server_side_encryption = _coalesce_optional_legacy_env(
            current=self.server_side_encryption,
            legacy_env="AUDIT_ARCHIVE_MINIO_SERVER_SIDE_ENCRYPTION",
        )


@dataclass(frozen=True)
class TraceWriteResult:
    object_key: str
    version_id: str  # MinIO version ID; non-empty only when bucket versioning is enabled
    etag: str
    written_at: datetime


class TraceObjectStore:
    """Async MinIO/S3-compatible adapter for immutable execution trace storage.

    Write-once semantics (AC-3):
      Bucket versioning is ENABLED at startup via ``ensure_bucket_ready()``.
      Each PUT produces a new version_id.  The prior object is retained and
      accessible via the version_id stored in TraceRecord.object_version.
      Direct overwrites are therefore impossible without a new version.

    Immutability (AC-3):
      Object Lock COMPLIANCE mode is recommended for regulated environments.
    """

    def __init__(self, settings: TraceObjectStoreSettings | None = None) -> None:
        self._settings = settings or TraceObjectStoreSettings()
        _validate_retention(self._settings)

    async def write(self, trace: ExecutionTrace) -> TraceWriteResult:
        """Serialise ``trace`` to JSON and PUT it to MinIO.

        Returns ``TraceWriteResult`` containing the MinIO version_id (AC-3).

        Object key pattern: ``traces/{tenant_id}/{YYYY}/{MM}/{request_id}.json``
        """
        key = _build_key(trace)
        payload = trace.model_dump_json(indent=None).encode()
        put_kwargs: dict[str, Any] = {
            "Bucket": self._settings.bucket,
            "Key": key,
            "Body": payload,
            "ContentType": _CONTENT_TYPE,
        }
        if self._settings.server_side_encryption:
            put_kwargs["ServerSideEncryption"] = self._settings.server_side_encryption

        async with _s3_client(self._settings) as s3:
            resp = await s3.put_object(**put_kwargs)

        version_id = resp.get("VersionId") or ""
        etag = (resp.get("ETag") or "").strip('"')
        written_at = datetime.now(tz=UTC)

        logger.info(
            "trace.written request_id=%s key=%s version=%s",
            trace.request_id,
            key,
            version_id,
        )
        return TraceWriteResult(
            object_key=key,
            version_id=version_id,
            etag=etag,
            written_at=written_at,
        )

    async def ensure_bucket_ready(self) -> None:
        """Idempotent startup check.

        1. Create bucket if absent.
        2. Enable versioning (required for write-once AC-3).
        3. Apply lifecycle expiry policy (AC-5).

        Called once during lifespan startup — not on every write.
        """
        async with _s3_client(self._settings) as s3:
            await _ensure_bucket_exists(s3, self._settings.bucket)
            await _ensure_versioning_enabled(s3, self._settings.bucket)
            await _apply_lifecycle_policy(s3, self._settings)

    async def read(
        self, object_key: str, version_id: str | None = None
    ) -> ExecutionTrace:
        """Retrieve and deserialise a trace from MinIO.

        Used by US-035 Replay Explorer.
        Pass ``version_id`` to retrieve a specific historical version (AC-3).
        """
        kwargs: dict[str, str] = {"Bucket": self._settings.bucket, "Key": object_key}
        if version_id:
            kwargs["VersionId"] = version_id

        async with _s3_client(self._settings) as s3:
            try:
                resp = await s3.get_object(**kwargs)
                body = await resp["Body"].read()
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code == "NoSuchKey":
                    raise TraceNotFoundError(object_key) from exc
                raise

        return ExecutionTrace.model_validate_json(body)


# ------------------------------------------------------------------ #
# Private helpers                                                      #
# ------------------------------------------------------------------ #


def _build_key(trace: ExecutionTrace) -> str:
    """Deterministic, partition-friendly object key.

    Pattern: ``traces/{tenant_id}/{YYYY}/{MM}/{request_id}.json``
    """
    ts = trace.timestamp
    return (
        f"traces/{trace.tenant_id}/"
        f"{ts.year:04d}/{ts.month:02d}/"
        f"{trace.request_id}.json"
    )


def _coalesce_legacy_env(*, current: str, default: str, legacy_env: str) -> str:
    legacy_value = os.environ.get(legacy_env, "")
    if current == default and legacy_value:
        return legacy_value
    return current


def _coalesce_optional_legacy_env(*, current: str | None, legacy_env: str) -> str | None:
    if current:
        return current
    legacy_value = os.environ.get(legacy_env, "")
    return legacy_value or None


def _validate_retention(settings: TraceObjectStoreSettings) -> None:
    if settings.retention_days < settings.retention_days_min:
        raise ValueError(
            f"TRACE_STORE_RETENTION_DAYS must be >= {settings.retention_days_min}. "
            f"Got {settings.retention_days}."
        )


def _s3_client(settings: TraceObjectStoreSettings) -> Any:  # noqa: ANN401
    """Return an async context manager producing an aiobotocore S3 client."""
    session = aiobotocore.session.get_session()
    return session.create_client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.region_name,
    )


async def _ensure_bucket_exists(s3: Any, bucket: str) -> None:  # noqa: ANN401
    try:
        await s3.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchBucket"):
            await s3.create_bucket(Bucket=bucket)
        else:
            raise


async def _ensure_versioning_enabled(s3: Any, bucket: str) -> None:  # noqa: ANN401
    resp = await s3.get_bucket_versioning(Bucket=bucket)
    status = resp.get("Status", "")
    if status != "Enabled":
        await s3.put_bucket_versioning(
            Bucket=bucket,
            VersioningConfiguration={"Status": "Enabled"},
        )


async def _apply_lifecycle_policy(
    s3: Any,  # noqa: ANN401
    settings: TraceObjectStoreSettings,
) -> None:
    """Apply an expiry rule so objects older than ``retention_days`` are deleted
    automatically by MinIO's lifecycle engine (AC-5).

    Rule ID is deterministic — re-applying is idempotent.
    """
    rule_id = f"contextiq-trace-expiry-{settings.retention_days}d"
    await s3.put_bucket_lifecycle_configuration(
        Bucket=settings.bucket,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": rule_id,
                    "Status": "Enabled",
                    "Filter": {"Prefix": "traces/"},
                    "Expiration": {"Days": settings.retention_days},
                    # Retain noncurrent (older) versions for the same window
                    "NoncurrentVersionExpiration": {
                        "NoncurrentDays": settings.retention_days
                    },
                }
            ]
        },
    )


class TraceNotFoundError(Exception):
    """Raised when a requested trace object does not exist in MinIO."""
