"""Standalone lifecycle helper for the execution trace bucket — TASK-US034-02.

Provides ``ensure_bucket_lifecycle()`` as an idempotent function that can be
called independently (e.g., from a migration script or admin CLI) in addition
to the startup path inside ``TraceObjectStore.ensure_bucket_ready()``.
"""
from __future__ import annotations

from src.audit.trace.object_store import (
    TraceObjectStoreSettings,
    _apply_lifecycle_policy,
    _ensure_bucket_exists,
    _ensure_versioning_enabled,
    _s3_client,
)


async def ensure_bucket_lifecycle(
    settings: TraceObjectStoreSettings | None = None,
) -> None:
    """Idempotent helper — creates bucket (if absent), enables versioning,
    and applies the lifecycle expiry rule.

    Safe to call multiple times; a second call with the same ``retention_days``
    simply re-PUT the same lifecycle rule (MinIO/S3 treats it as an upsert).
    """
    cfg = settings or TraceObjectStoreSettings()
    async with _s3_client(cfg) as s3:
        await _ensure_bucket_exists(s3, cfg.bucket)
        await _ensure_versioning_enabled(s3, cfg.bucket)
        await _apply_lifecycle_policy(s3, cfg)
