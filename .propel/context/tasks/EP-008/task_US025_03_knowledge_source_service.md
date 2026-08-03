# TASK-US025-03 — `KnowledgeSourceRepository` and `KnowledgeSourceService`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US025-03 |
| User Story | US-025 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `KnowledgeSourceRepository` (raw PostgreSQL CRUD via SQLAlchemy async) and `KnowledgeSourceService` (business logic: Vault validation, 400/409 guards, active toggle, and Kafka event emission on creation). This is the service layer consumed by the Admin API router (TASK-US025-04).

## Implementation Details

**Technology:** Python 3.11+, SQLAlchemy 2.x async, `aiokafka`, FastAPI `HTTPException`

**File locations:**
- `src/knowledge_sources/repositories/knowledge_source_repository.py` — `KnowledgeSourceRepository`
- `src/knowledge_sources/services/knowledge_source_service.py` — `KnowledgeSourceService`
- `tests/knowledge_sources/test_knowledge_source_service.py`

**`KnowledgeSourceRepository`:**

```python
# src/knowledge_sources/repositories/knowledge_source_repository.py
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.knowledge_sources.models.knowledge_source import KnowledgeSourceRecord
from src.knowledge_sources.schemas.knowledge_source import KnowledgeSourceCreate, SourceStatus

class KnowledgeSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, source_id: UUID) -> KnowledgeSourceRecord | None:
        result = await self._session.execute(
            select(KnowledgeSourceRecord).where(KnowledgeSourceRecord.id == source_id)
        )
        return result.scalar_one_or_none()

    async def get_by_connector_and_scope(
        self, connector_type: str, scope: str
    ) -> KnowledgeSourceRecord | None:
        result = await self._session.execute(
            select(KnowledgeSourceRecord).where(
                KnowledgeSourceRecord.connector_type == connector_type,
                KnowledgeSourceRecord.scope          == scope,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, payload: KnowledgeSourceCreate) -> KnowledgeSourceRecord:
        record = KnowledgeSourceRecord(
            connector_type         = payload.connector_type,
            credentials_vault_path = payload.credentials_vault_path,
            scope                  = payload.scope,
            sync_schedule          = payload.sync_schedule,
            token_budget_weight    = payload.token_budget_weight,
            status                 = SourceStatus.ACTIVE,
            is_active              = True,
        )
        self._session.add(record)
        await self._session.flush()   # populate DB-generated id/timestamps
        return record

    async def list_all(self) -> list[KnowledgeSourceRecord]:
        result = await self._session.execute(
            select(KnowledgeSourceRecord).order_by(KnowledgeSourceRecord.created_at.desc())
        )
        return list(result.scalars().all())

    async def set_active(self, source_id: UUID, is_active: bool) -> KnowledgeSourceRecord | None:
        record = await self.get_by_id(source_id)
        if record is None:
            return None
        record.is_active = is_active
        record.status    = SourceStatus.ACTIVE if is_active else SourceStatus.INACTIVE
        await self._session.flush()
        return record
```

**`KnowledgeSourceService`:**

```python
# src/knowledge_sources/services/knowledge_source_service.py
import json
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.knowledge_sources.repositories.knowledge_source_repository import KnowledgeSourceRepository
from src.knowledge_sources.schemas.knowledge_source import (
    KnowledgeSourceCreate, KnowledgeSourceResponse,
)
from src.knowledge_sources.vault_validator import VaultPathValidator

_KAFKA_TOPIC = "knowledge.source.created"

class KnowledgeSourceService:
    def __init__(
        self,
        session:   AsyncSession,
        validator: VaultPathValidator | None = None,
    ) -> None:
        self._repo      = KnowledgeSourceRepository(session)
        self._session   = session
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
                status_code = 409,
                detail      = (
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

    async def toggle_active(self, source_id: UUID, is_active: bool) -> KnowledgeSourceResponse:
        record = await self._repo.set_active(source_id, is_active)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Knowledge source {source_id} not found")
        await self._session.commit()
        return KnowledgeSourceResponse.model_validate(record)

    async def _emit_creation_event(
        self, source_id, payload: KnowledgeSourceCreate
    ) -> None:
        """Emit Kafka event so downstream indexing service picks up the new source (AC-6)."""
        from src.events.producer import get_kafka_producer
        event = {
            "event_type":     "knowledge_source_created",
            "source_id":      str(source_id),
            "connector_type": payload.connector_type,
            "scope":          payload.scope,
        }
        producer = await get_kafka_producer()
        await producer.send_and_wait(_KAFKA_TOPIC, value=json.dumps(event).encode())
```

**Session ownership:**

`KnowledgeSourceService` does not own the session lifecycle. `commit()` is called after `flush()` to ensure the record ID is available before the Kafka event is published. If Kafka `send_and_wait()` fails after the DB commit, the record remains in the DB without the downstream event — this is acceptable at Phase 2 (at-least-once delivery is guaranteed by the scheduler picking up the source on its first sync window). A transactional outbox pattern is deferred to Phase 3.

## Acceptance Criteria

- [ ] `create()` raises `HTTP 400` when `VaultPathValidator.validate()` returns `valid=False`
- [ ] `create()` raises `HTTP 409` when a source with the same `(connector_type, scope)` already exists
- [ ] `create()` raises `HTTP 409` before calling `VaultPathValidator` to avoid redundant Vault calls on duplicate
- [ ] `create()` commits the DB record before emitting the Kafka event
- [ ] `list_all()` returns records ordered by `created_at DESC`
- [ ] `toggle_active(id, False)` sets `is_active=False` and `status="inactive"`
- [ ] `toggle_active(unknown_id, ...)` raises `HTTP 404`

## Dependencies

- TASK-US025-01 (`KnowledgeSourceRecord`, `KnowledgeSourceCreate`, `KnowledgeSourceResponse`, `SourceStatus`)
- TASK-US025-02 (`VaultPathValidator`, `VaultValidationResult`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit tests use in-memory async SQLite session and `AsyncMock` for Vault validator and Kafka
- [ ] `mypy --strict` passes; no `ruff` lint errors
