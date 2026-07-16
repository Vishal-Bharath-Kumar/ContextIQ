"""KnowledgeSourceService — business logic for knowledge source management.

TASK-US025-03: Vault validation, 400/409 guards, active toggle, and Kafka
event emission on creation.  Consumed by the Admin API router (TASK-US025-04).

Session ownership note: KnowledgeSourceService does not own the session
lifecycle.  commit() is called after flush() to ensure the record ID is
available before the Kafka event is published.  If Kafka send_and_wait()
fails after the DB commit, the record remains in the DB without the downstream
event — acceptable at Phase 2 (at-least-once delivery is guaranteed by the
scheduler picking up the source on its first sync window).  A transactional
outbox pattern is deferred to Phase 3.
"""
from __future__ import annotations

import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_sources.repositories.knowledge_source_repository import (
    KnowledgeSourceRepository,
)
from src.knowledge_sources.schemas.knowledge_source import (
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
)
from src.knowledge_sources.vault_validator import VaultPathValidator

_KAFKA_TOPIC = "knowledge.source.created"


class KnowledgeSourceService:
    def __init__(
        self,
        session: AsyncSession,
        validator: VaultPathValidator | None = None,
    ) -> None:
        self._repo = KnowledgeSourceRepository(session)
        self._session = session
        self._validator = validator or VaultPathValidator()

    async def create(self, payload: KnowledgeSourceCreate) -> KnowledgeSourceResponse:
        # AC-5: validate Vault path before writing to DB
        vault_result = await self._validator.validate(payload.credentials_vault_path)
        if not vault_result.valid:
            raise HTTPException(status_code=400, detail=vault_result.message)

        # 409 guard: duplicate (connector_type, scope)
        existing = await self._repo.get_by_connector_and_scope(
            payload.connector_type, payload.scope
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"A knowledge source for connector '{payload.connector_type}' "
                    f"with scope '{payload.scope}' is already registered."
                ),
            )

        record = await self._repo.create(payload)
        await self._session.commit()
        await self._emit_creation_event(record.id, payload)
        return KnowledgeSourceResponse.model_validate(record)

    async def list_all(self) -> list[KnowledgeSourceResponse]:
        records = await self._repo.list_all()
        return [KnowledgeSourceResponse.model_validate(r) for r in records]

    async def toggle_active(
        self, source_id: UUID, is_active: bool
    ) -> KnowledgeSourceResponse:
        record = await self._repo.set_active(source_id, is_active)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"Knowledge source {source_id} not found",
            )
        await self._session.commit()
        return KnowledgeSourceResponse.model_validate(record)

    async def _emit_creation_event(
        self, source_id: UUID, payload: KnowledgeSourceCreate
    ) -> None:
        """Emit Kafka event so downstream indexing service picks up the new source (AC-6)."""
        from src.events.producer import get_kafka_producer

        event = {
            "event_type": "knowledge_source_created",
            "source_id": str(source_id),
            "connector_type": payload.connector_type,
            "scope": payload.scope,
        }
        producer = await get_kafka_producer()
        await producer.send_and_wait(
            _KAFKA_TOPIC, value=json.dumps(event).encode()
        )
