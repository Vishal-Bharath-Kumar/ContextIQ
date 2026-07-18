"""HealthCheckService — runs a live connectivity probe against a connector — TASK-US039-04."""
from __future__ import annotations

import importlib
import time
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_sources.repositories.knowledge_source_repository import (
    KnowledgeSourceRepository,
)
from src.knowledge_sources.schemas.connector_audit import HealthCheckResponse


class HealthCheckService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = KnowledgeSourceRepository(session)

    async def run(self, source_id: UUID) -> HealthCheckResponse:
        """Invoke `health_check()` on the registered connector implementation.

        Returns a `HealthCheckResponse` with ``ok=True`` on success or
        ``ok=False`` (HTTP 200) on connector error.  Raises HTTP 404 when
        the knowledge-source record does not exist and HTTP 501 when the
        connector type has no implementation.
        """
        record = await self._repo.get_by_id(source_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connector not found",
            )

        try:
            module = importlib.import_module(
                f"src.connectors.{record.connector_type}.connector"
            )
            cls = getattr(
                module, f"{record.connector_type.capitalize()}Connector"
            )
            connector = cls(
                vault_path=record.credentials_vault_path,
                scope=record.scope,
            )
        except (ImportError, AttributeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=f"Connector type '{record.connector_type}' not implemented",
            ) from exc

        t0 = time.monotonic()
        try:
            await connector.health_check()
            latency_ms = int((time.monotonic() - t0) * 1000)
            return HealthCheckResponse(ok=True, latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return HealthCheckResponse(ok=False, latency_ms=latency_ms, detail=str(exc))
