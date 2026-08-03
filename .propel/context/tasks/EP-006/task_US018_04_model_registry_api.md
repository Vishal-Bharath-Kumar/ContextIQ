# TASK-US018-04 — `POST /v1/models` and `GET /v1/models` API Endpoints

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US018-04 |
| User Story | US-018 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend / API |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Register the `POST /v1/models` and `GET /v1/models` FastAPI routes that expose the Model Capability Registry to admins. `POST` delegates to `ModelRegistryService.register()` and returns 201 on success or 409 on duplicate. `GET` serves the active model list from the Redis cache (TASK-US018-05) with a DB fallback, sorted by cost ASC.

## Implementation Details

**Technology:** Python 3.11+, FastAPI, Pydantic v2

**File locations:**
- `src/model_registry/routers/model_router.py` — route definitions
- `src/model_registry/dependencies.py` — `get_model_registry_service()` FastAPI dependency
- `tests/model_registry/test_model_router.py` — tests with `httpx.AsyncClient`

**`dependencies.py`:**

```python
# src/model_registry/dependencies.py
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio           import Redis
from src.db.session          import get_async_session   # shared DB dependency
from src.cache.redis         import get_redis_client    # shared Redis dependency
from src.model_registry.services.model_registry_service import ModelRegistryService

async def get_model_registry_service(
    session: AsyncSession = Depends(get_async_session),
    redis:   Redis        = Depends(get_redis_client),
) -> ModelRegistryService:
    return ModelRegistryService(session=session, redis=redis)
```

**`model_router.py`:**

```python
# src/model_registry/routers/model_router.py
from fastapi import APIRouter, Depends, status
from src.model_registry.schemas.model_definition     import ModelRegistration, ModelDefinition
from src.model_registry.dependencies                  import get_model_registry_service
from src.model_registry.services.model_registry_service import ModelRegistryService
from src.model_registry.cache.model_cache            import ModelListCache
from src.cache.redis                                  import get_redis_client
from redis.asyncio import Redis

router = APIRouter(prefix="/v1/models", tags=["Model Registry"])

@router.post(
    "",
    status_code = status.HTTP_201_CREATED,
    response_model = ModelDefinition,
    summary = "Register a new AI model in the capability registry",
)
async def register_model(
    payload:  ModelRegistration,
    service:  ModelRegistryService = Depends(get_model_registry_service),
) -> ModelDefinition:
    """Register a new AI model. Returns HTTP 409 if `model_id` is already registered."""
    return await service.register(payload)


@router.get(
    "",
    response_model = list[ModelDefinition],
    summary = "List all active registered models sorted by cost ASC",
)
async def list_models(
    service: ModelRegistryService = Depends(get_model_registry_service),
    redis:   Redis                = Depends(get_redis_client),
) -> list[ModelDefinition]:
    """Return active models from cache; fall back to DB on cache miss."""
    cache = ModelListCache(redis)
    cached = await cache.get()
    if cached is not None:
        return cached
    models = await service.list_active()
    await cache.set(models)
    return models
```

**Router registration in app factory:**

```python
# src/gateway/main.py  (extend existing app factory — do NOT replace)
from src.model_registry.routers.model_router import router as model_router
app.include_router(model_router)
```

**Authentication scope:**
Both endpoints require an admin JWT claim (`role = "admin"`) enforced by the JWT middleware (TASK-US004-01). Requests from non-admin callers receive HTTP 403. This is enforced by a route dependency, not inline logic:

```python
from src.gateway.middleware.auth import require_admin_role

@router.post("", dependencies=[Depends(require_admin_role)], ...)
@router.get("",  dependencies=[Depends(require_admin_role)], ...)
```

## Acceptance Criteria

- [ ] `POST /v1/models` with a valid payload returns HTTP 201 and a `ModelDefinition` body
- [ ] `POST /v1/models` with a duplicate `model_id` returns HTTP 409 with an error message
- [ ] `POST /v1/models` with an invalid payload (missing required field) returns HTTP 422
- [ ] `GET /v1/models` returns an array of `ModelDefinition` objects sorted by `cost_per_1k_tokens ASC`
- [ ] `GET /v1/models` is served from Redis cache on a second request (cache hit verified by mock call count)
- [ ] Non-admin requests to either endpoint return HTTP 403

## Dependencies

- TASK-US018-01 (`ModelRegistration`, `ModelDefinition` — request/response types)
- TASK-US018-03 (`ModelRegistryService.register()`, `list_active()`)
- TASK-US018-05 (`ModelListCache.get()`, `set()` — cache read/write in `GET` handler)
- TASK-US004-01 (JWT middleware + `require_admin_role` dependency)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] API contract documented in OpenAPI spec (auto-generated via FastAPI)
- [ ] Integration tests use `httpx.AsyncClient` with mocked service layer
- [ ] `mypy --strict` passes; no `ruff` lint errors
