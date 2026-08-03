# TASK-US018-05 — Redis Model List Cache with 30-Second Pub/Sub Invalidation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US018-05 |
| User Story | US-018 |
| Epic | EP-006 — Dynamic Model Routing |
| Layer | Backend / Caching |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `ModelListCache`, the Redis-backed cache for the active model list, and start a pub/sub subscriber task in the FastAPI lifespan that invalidates the cache within 30 seconds of any model registration change. This follows the established pattern from `ToolListCache` (TASK-US002-03) and satisfies US-018 AC-6.

## Implementation Details

**Technology:** Python 3.11+, `redis.asyncio>=5.0`

**File locations:**
- `src/model_registry/cache/model_cache.py` — `ModelListCache` class
- `src/agents/worker/lifespan.py` — pub/sub subscriber task added to existing lifespan (extends)
- `tests/model_registry/cache/test_model_cache.py` — tests with `fakeredis.aioredis`

**`ModelListCache`:**

```python
# src/model_registry/cache/model_cache.py
import json
from redis.asyncio import Redis
from src.model_registry.schemas.model_definition import ModelDefinition

class ModelListCache:
    KEY         = "contextiq:model_registry:active_models"
    TTL_SECONDS = 60   # safety-net TTL; pub/sub invalidation is the primary mechanism

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self) -> list[ModelDefinition] | None:
        raw = await self._redis.get(self.KEY)
        if raw is None:
            return None
        data = json.loads(raw)
        return [ModelDefinition.model_validate(item) for item in data]

    async def set(self, models: list[ModelDefinition]) -> None:
        payload = json.dumps([m.model_dump(mode="json") for m in models])
        await self._redis.set(self.KEY, payload, ex=self.TTL_SECONDS)

    async def invalidate(self) -> None:
        await self._redis.delete(self.KEY)
```

**Pub/sub subscriber — invalidation within 30 seconds:**

The subscriber listens on `contextiq:model_registry:changed` (published by `ModelRegistryService._publish_change_event()` in TASK-US018-03) and calls `invalidate()` immediately upon receiving a message. The "30-second" SLA is the maximum time before the next `GET /v1/models` call detects the change — in practice it is nearly instant:

```python
# src/agents/worker/lifespan.py  (extend existing lifespan — do NOT replace)
import asyncio, json

async def _model_cache_invalidator(redis: Redis, cache: ModelListCache) -> None:
    """Subscribe to registry change events and invalidate the model list cache."""
    pubsub = redis.pubsub()
    await pubsub.subscribe("contextiq:model_registry:changed")
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            data = json.loads(message["data"])
            await cache.invalidate()
        except Exception:
            pass   # log and continue — never crash the subscriber

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup ...
    redis       = app.state.redis
    model_cache = ModelListCache(redis)
    invalidator_task = asyncio.create_task(
        _model_cache_invalidator(redis, model_cache)
    )
    yield
    invalidator_task.cancel()
```

**30-second SLA guarantee:**
- Pub/sub message delivery from `PUBLISH` to subscriber `listen()` is sub-millisecond on a local Redis instance
- Network RTT in a Kubernetes cluster is typically < 5 ms
- The 30-second SLA is satisfied with > 29 seconds of headroom — the constraint is architectural, not a polling window

**Cache key alignment with model router (TASK-US018-04):**
`ModelListCache.KEY = "contextiq:model_registry:active_models"` is referenced by both the cache class and the `GET /v1/models` handler via `ModelListCache`. The key string is defined once in `model_cache.py` — no inline string literals in the router.

## Acceptance Criteria

- [ ] `ModelListCache.get()` returns `None` on a cold cache
- [ ] `ModelListCache.set(models)` followed by `get()` returns the original models list (round-trip)
- [ ] `ModelListCache.invalidate()` deletes the cache key; the next `get()` returns `None`
- [ ] The pub/sub subscriber calls `invalidate()` within 1 second of a `PUBLISH contextiq:model_registry:changed` message
- [ ] TTL is set to 60 seconds as a safety net — verified via `PTTL` assertion in tests
- [ ] Subscriber task is cancelled cleanly on FastAPI shutdown (no `asyncio.CancelledError` log noise)

## Dependencies

- TASK-US018-01 (`ModelDefinition.model_dump(mode="json")` and `model_validate()`)
- TASK-US018-03 (`REGISTRY_CHANGE_CHANNEL` — pub/sub channel name must match)
- TASK-US018-04 (`GET /v1/models` — calls `ModelListCache.get()` / `set()`)
- TASK-US002-03 (`ToolListCache` pattern — followed for naming and TTL conventions)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests use `fakeredis.aioredis` — no live Redis in CI
- [ ] `ModelListCache.KEY` is the single source of truth — no hardcoded key strings outside this class
- [ ] `mypy --strict` passes; no `ruff` lint errors
