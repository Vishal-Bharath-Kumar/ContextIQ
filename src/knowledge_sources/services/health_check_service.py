"""HealthCheckService — runs a live connectivity probe against a connector — TASK-US039-04."""
from __future__ import annotations

import time
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.retrieval.connector_loader import CONNECTOR_CLASS_MAP
from src.knowledge_sources.config import KnowledgeSourceSettings
from src.knowledge_sources.repositories.knowledge_source_repository import (
    KnowledgeSourceRepository,
)
from src.knowledge_sources.schemas.connector_audit import HealthCheckResponse


class HealthCheckService:
    def __init__(
        self,
        session: AsyncSession,
        vault_settings: KnowledgeSourceSettings | None = None,
    ) -> None:
        self._repo = KnowledgeSourceRepository(session)
        self._vault_settings = vault_settings or KnowledgeSourceSettings()

    async def run(self, source_id: UUID) -> HealthCheckResponse:
        """Authenticate and invoke `health_check()` on the registered connector.

        Returns a `HealthCheckResponse` with ``ok`` mirroring the connector's
        own ``HealthStatus.healthy`` flag — ``ok=False`` (HTTP 200) on
        connector/auth error, never raising for connector-side failures.
        Raises HTTP 404 when the knowledge-source record does not exist and
        HTTP 501 when the connector type has no implementation.
        """
        record = await self._repo.get_by_id(source_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connector not found",
            )

        mapping = CONNECTOR_CLASS_MAP.get(record.connector_type)
        if mapping is None:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=f"Connector type '{record.connector_type}' not implemented",
            )
        connector_cls, config_cls = mapping

        t0 = time.monotonic()
        try:
            # The platform's shared AppRole (KNOWLEDGE_SOURCE_VAULT_*) authenticates
            # to Vault; each connector config's own per-type env vars (e.g.
            # GITHUB_CONNECTOR_VAULT_*) are not populated in this deployment, so we
            # inject the platform Vault address/role/secret explicitly rather than
            # relying on the connector config's unreachable defaults.
            connector = connector_cls(
                config=config_cls(
                    vault_path=record.credentials_vault_path,
                    vault_addr=self._vault_settings.vault_addr,
                    vault_role_id=self._vault_settings.vault_role_id,
                    vault_secret_id=self._vault_settings.vault_secret_id,
                )
            )
            await connector.authenticate()
            result = await connector.health_check()
            latency_ms = int((time.monotonic() - t0) * 1000)
            return HealthCheckResponse(
                ok=result.healthy,
                latency_ms=latency_ms,
                detail=None if result.healthy else result.message,
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return HealthCheckResponse(ok=False, latency_ms=latency_ms, detail=str(exc))
