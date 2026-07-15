"""
ArchiveSettings — pydantic-settings config for the MinIO audit archiver.

All credentials are injected by Vault Agent at runtime via environment
variables; no secrets are hard-coded (OWASP A02).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ArchiveSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUDIT_ARCHIVE_",
        env_file=".env",
        extra="ignore",
    )

    minio_endpoint:   str = "http://minio.minio.svc.cluster.local:9000"
    minio_bucket:     str = "contextiq-audit-archive"
    # Credentials injected by Vault Agent — never hard-coded (OWASP A02)
    minio_access_key: str = ""   # AUDIT_ARCHIVE_MINIO_ACCESS_KEY
    minio_secret_key: str = ""   # AUDIT_ARCHIVE_MINIO_SECRET_KEY
    minio_region:     str = "us-east-1"
