# TASK-US034-02 — `TraceObjectStore` (MinIO Write-Once, Versioning, Lifecycle Policy)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US034-02 |
| User Story | US-034 |
| Epic | EP-011 — AI Execution Replay |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `TraceObjectStore` — the async MinIO/S3-compatible adapter that writes execution traces as immutable JSON objects (AC-1), enforces write-once semantics via object versioning (AC-3), and applies a lifecycle expiry policy ensuring 90-day minimum retention (AC-5). The object key scheme is deterministic — derived from `tenant_id`, date, and `request_id` — enabling efficient prefix-scoped listing by US-035. Consumed by `trace_writer_node` (TASK-US034-04) via an async background task (AC-6).

## Implementation Details

**Technology:** Python 3.11+, `aiobotocore>=2.13` (S3-compatible), `pydantic-settings`, `botocore.exceptions`

**File locations:**
- `src/audit/trace/object_store.py` — `TraceObjectStore`, `TraceObjectStoreSettings`, `TraceWriteResult`
- `src/audit/trace/lifecycle.py` — `ensure_bucket_lifecycle()` — idempotent lifecycle rule setup
- `tests/audit/test_trace_object_store.py`

---

### Settings

```python
# src/audit/trace/object_store.py  (settings embedded; no separate file)
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict


class TraceObjectStoreSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix = "TRACE_STORE_",
        env_file   = ".env",
    )

    endpoint_url:         str  = "http://minio:9000"
    bucket:               str  = "contextiq-traces"
    aws_access_key_id:    str  = "minioadmin"
    aws_secret_access_key: str = "minioadmin"
    region_name:          str  = "us-east-1"

    # AC-5: retention window (days); minimum 90, default 365
    retention_days:       int  = 365
    retention_days_min:   int  = 90   # validated in __init__; never configurable below 90
```

---

### `TraceObjectStore`

```python
# src/audit/trace/object_store.py (continued)
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from datetime    import datetime, timezone

import aiobotocore.session
from botocore.exceptions import ClientError

from src.audit.trace.schemas   import ExecutionTrace

logger = logging.getLogger(__name__)

_CONTENT_TYPE = "application/json"


@dataclass(frozen=True)
class TraceWriteResult:
    object_key:     str
    version_id:     str    # MinIO version ID; non-empty only when bucket versioning is enabled
    etag:           str
    written_at:     datetime


class TraceObjectStore:
    """
    Async MinIO/S3-compatible adapter for immutable execution trace storage.

    Write-once semantics (AC-3):
      Bucket versioning is ENABLED at startup via `ensure_bucket_versioning()`.
      Each PUT produces a new version_id.  The prior object is retained and
      accessible via the version_id stored in TraceRecord.object_version.
      Direct overwrites are therefore impossible without a new version — satisfying
      the "updates create a new version, not overwrites" requirement.

    Immutability (AC-3):
      Object Lock COMPLIANCE mode is recommended for regulated environments.
      The `lock_mode` setting defaults to None (disabled) to avoid requiring
      Object Lock–enabled buckets in development; enable via TRACE_STORE_LOCK_MODE=COMPLIANCE.
    """

    def __init__(self, settings: TraceObjectStoreSettings | None = None) -> None:
        self._settings = settings or TraceObjectStoreSettings()
        _validate_retention(self._settings)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def write(self, trace: ExecutionTrace) -> TraceWriteResult:
        """
        Serialise `trace` to JSON and PUT it to MinIO.
        Returns `TraceWriteResult` containing the MinIO version_id (AC-3).

        Object key pattern:
          traces/{tenant_id}/{YYYY}/{MM}/{request_id}.json
        """
        key     = _build_key(trace)
        payload = trace.model_dump_json(indent=None).encode()

        async with _s3_client(self._settings) as s3:
            resp = await s3.put_object(
                Bucket      = self._settings.bucket,
                Key         = key,
                Body        = payload,
                ContentType = _CONTENT_TYPE,
                # Server-side encryption (EP-TECH-002 / NFR — encryption at rest)
                ServerSideEncryption = "AES256",
            )

        version_id = resp.get("VersionId") or ""
        etag       = (resp.get("ETag") or "").strip('"')
        written_at = datetime.now(tz=timezone.utc)

        logger.info(
            "trace.written request_id=%s key=%s version=%s",
            trace.request_id, key, version_id,
        )
        return TraceWriteResult(
            object_key = key,
            version_id = version_id,
            etag       = etag,
            written_at = written_at,
        )

    async def ensure_bucket_ready(self) -> None:
        """
        Idempotent startup check:
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
        """
        Retrieve and deserialise a trace from MinIO.
        Used by US-035 Replay Explorer.
        Pass `version_id` to retrieve a specific historical version (AC-3).
        """
        kwargs: dict = {"Bucket": self._settings.bucket, "Key": object_key}
        if version_id:
            kwargs["VersionId"] = version_id

        async with _s3_client(self._settings) as s3:
            try:
                resp = await s3.get_object(**kwargs)
                body = await resp["Body"].read()
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                raise TraceNotFoundError(object_key) from exc if code == "NoSuchKey" else exc

        return ExecutionTrace.model_validate_json(body)


# ------------------------------------------------------------------ #
# Private helpers                                                      #
# ------------------------------------------------------------------ #

def _build_key(trace: ExecutionTrace) -> str:
    """
    Deterministic, partition-friendly object key.
    Pattern: traces/{tenant_id}/{YYYY}/{MM}/{request_id}.json
    """
    ts = trace.timestamp
    return (
        f"traces/{trace.tenant_id}/"
        f"{ts.year:04d}/{ts.month:02d}/"
        f"{trace.request_id}.json"
    )


def _validate_retention(settings: TraceObjectStoreSettings) -> None:
    if settings.retention_days < settings.retention_days_min:
        raise ValueError(
            f"TRACE_STORE_RETENTION_DAYS must be >= {settings.retention_days_min}. "
            f"Got {settings.retention_days}."
        )


def _s3_client(settings: TraceObjectStoreSettings):
    """Return an async context manager producing an aiobotocore S3 client."""
    session = aiobotocore.session.get_session()
    return session.create_client(
        "s3",
        endpoint_url          = settings.endpoint_url,
        aws_access_key_id     = settings.aws_access_key_id,
        aws_secret_access_key = settings.aws_secret_access_key,
        region_name           = settings.region_name,
    )


async def _ensure_bucket_exists(s3, bucket: str) -> None:
    try:
        await s3.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchBucket"):
            await s3.create_bucket(Bucket=bucket)
        else:
            raise


async def _ensure_versioning_enabled(s3, bucket: str) -> None:
    resp   = await s3.get_bucket_versioning(Bucket=bucket)
    status = resp.get("Status", "")
    if status != "Enabled":
        await s3.put_bucket_versioning(
            Bucket                   = bucket,
            VersioningConfiguration  = {"Status": "Enabled"},
        )


async def _apply_lifecycle_policy(
    s3, settings: TraceObjectStoreSettings
) -> None:
    """
    Apply an expiry rule so objects older than `retention_days` are deleted
    automatically by MinIO's lifecycle engine (AC-5).
    Rule ID is deterministic — re-applying is idempotent.
    """
    rule_id = f"contextiq-trace-expiry-{settings.retention_days}d"
    await s3.put_bucket_lifecycle_configuration(
        Bucket                    = settings.bucket,
        LifecycleConfiguration    = {
            "Rules": [
                {
                    "ID":     rule_id,
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
```

## Acceptance Criteria

- [ ] `TraceObjectStore.write()` returns a `TraceWriteResult` with a non-empty `version_id` when bucket versioning is enabled (AC-1, AC-3)
- [ ] `TraceObjectStore.write()` sets `ServerSideEncryption="AES256"` on every PUT (EP-TECH-002)
- [ ] `_build_key()` produces `traces/{tenant_id}/{YYYY}/{MM}/{request_id}.json` — deterministic, no randomness in key path
- [ ] `TraceObjectStore.ensure_bucket_ready()` enables versioning and applies the lifecycle expiry rule in a single startup call (AC-3, AC-5)
- [ ] `_validate_retention()` raises `ValueError` when `retention_days < 90` (AC-5 floor)
- [ ] `TraceObjectStore.read()` accepts an optional `version_id` to retrieve historical versions (AC-3)
- [ ] `_apply_lifecycle_policy()` is idempotent — a second call with the same `retention_days` does not error

## Dependencies

- TASK-US034-01 (`ExecutionTrace`, `TraceWriteResult`)
- MinIO sidecar (tests mock via `moto[s3]` or `respx` against `aiobotocore`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
