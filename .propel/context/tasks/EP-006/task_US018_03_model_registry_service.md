# TASK-US018-03 — `ModelRegistryRepository` and `ModelRegistryService` (CRUD + 409 Guard)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US018-03 |
| User Story | US-018 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement the async repository (raw DB queries) and service layer (business logic + 409 conflict guard) for the Model Capability Registry. The service is the single call site for all model CRUD operations; it is consumed by the API router (TASK-US018-04) and publishes a Redis pub/sub invalidation event after every mutating operation.

## Implementation Details

**Technology:** Python 3.11+, SQLAlchemy 2.x async, `redis.asyncio`

**File locations:**
- `src/model_registry/repositories/model_repository.py` — `ModelRepository`
- `src/model_registry/services/model_registry_service.py` — `ModelRegistryService`
- `tests/model_registry/test_model_registry_service.py`

**`ModelRepository`:**

```python
# src/model_registry/repositories/model_repository.py
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.model_registry.models.model    import ModelRecord
from src.model_registry.schemas.model_definition import ModelRegistration

class ModelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_model_id(self, model_id: str) -> ModelRecord | None:
        result = await self._session.execute(
            select(ModelRecord).where(ModelRecord.model_id == model_id)
        )
        return result.scalar_one_or_none()

    async def create(self, registration: ModelRegistration) -> ModelRecord:
        record = ModelRecord(
            model_id           = registration.model_id,
            provider           = registration.provider,
            context_window     = registration.context_window,
            cost_per_1k_tokens = registration.cost_per_1k_tokens,
            latency_tier       = registration.latency_tier,
            capabilities       = [c.value for c in registration.capabilities],
            is_active          = registration.is_active,
        )
        self._session.add(record)
        await self._session.flush()   # get DB-generated id/timestamps before commit
        return record

    async def list_active(self) -> list[ModelRecord]:
        result = await self._session.execute(
            select(ModelRecord)
            .where(ModelRecord.is_active == True)           # noqa: E712
            .order_by(ModelRecord.cost_per_1k_tokens.asc())
        )
        return list(result.scalars().all())
```

**`ModelRegistryService`:**

```python
# src/model_registry/services/model_registry_service.py
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from src.model_registry.repositories.model_repository  import ModelRepository
from src.model_registry.schemas.model_definition        import ModelRegistration, ModelDefinition

REGISTRY_CHANGE_CHANNEL = "contextiq:model_registry:changed"   # mirrors tool registry pattern

class ModelRegistryService:
    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self._repo  = ModelRepository(session)
        self._redis = redis

    async def register(self, registration: ModelRegistration) -> ModelDefinition:
        existing = await self._repo.get_by_model_id(registration.model_id)
        if existing is not None:
            raise HTTPException(
                status_code = 409,
                detail      = f"Model '{registration.model_id}' is already registered.",
            )
        record = await self._repo.create(registration)
        await self._session.commit()
        await self._publish_change_event(registration.model_id)
        return ModelDefinition.model_validate(record)

    async def list_active(self) -> list[ModelDefinition]:
        records = await self._repo.list_active()
        return [ModelDefinition.model_validate(r) for r in records]

    async def _publish_change_event(self, model_id: str) -> None:
        import json
        payload = json.dumps({"event": "model_registered", "model_id": model_id})
        await self._redis.publish(REGISTRY_CHANGE_CHANNEL, payload)
```

**Session and Redis injection:**
Both `AsyncSession` and `Redis` are injected via FastAPI dependencies (following the pattern from EP-001). The service does not own the session lifecycle — the router's dependency closes the session after each request.

**`_session` attribute fix:**
Note `self._session = session` must be added to `__init__`:
```python
def __init__(self, session: AsyncSession, redis: Redis) -> None:
    self._session = session
    self._repo    = ModelRepository(session)
    self._redis   = redis
```

## Acceptance Criteria

- [ ] `register()` returns a `ModelDefinition` with `id`, `created_at`, `updated_at` populated from DB
- [ ] `register()` raises `HTTP 409` when `model_id` is already present in the DB
- [ ] `list_active()` returns only `is_active=True` models, sorted by `cost_per_1k_tokens ASC`
- [ ] `_publish_change_event()` publishes a JSON message to `contextiq:model_registry:changed` within 100 ms
- [ ] DB session is committed before the pub/sub event is published
- [ ] All tests use `AsyncMock` for Redis and an in-memory SQLite async session — no live DB/Redis in CI

## Dependencies

- TASK-US018-01 (`ModelRegistration`, `ModelDefinition`)
- TASK-US018-02 (`ModelRecord` ORM model)
- TASK-US002-02 (pub/sub channel pattern — `REGISTRY_CHANGE_CHANNEL` mirrors `contextiq:tool_registry:changed`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 85% for both `model_repository.py` and `model_registry_service.py`
- [ ] Tests cover: successful registration, duplicate 409, list sorting, pub/sub publish
- [ ] `mypy --strict` passes; no `ruff` lint errors
