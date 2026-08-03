# TASK-US002-03 — Cache Tool List in Redis with 30-Second Change Propagation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US002-03 |
| User Story | US-002 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend / Caching |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement a Redis-backed caching layer for the tool registry so that `tools/list` is served from in-memory cache, and cache entries are invalidated within 30 seconds of any tool registration change. This satisfies both the 200 ms latency requirement and the change-propagation SLA.

## Implementation Details

**Technology:** Python 3.11+, `redis.asyncio`, JSON serialization, Redis pub/sub

**File locations:**
- `src/registry/cache/tool_cache.py` — `ToolListCache` class
- `src/gateway/lifespan.py` — starts the Redis pub/sub subscriber task in app lifespan
- `tests/registry/test_tool_cache.py` — unit tests with `fakeredis`

**Cache key design:**
```
contextiq:tool_registry:active_tools   → JSON-serialized list[ToolDefinition]
TTL: 60 seconds (safety net; invalidation is the primary mechanism)
```

**Cache operations:**

```python
class ToolListCache:
    KEY = "contextiq:tool_registry:active_tools"
    TTL_SECONDS = 60

    async def get(self) -> list[ToolDefinition] | None:
        raw = await self.redis.get(self.KEY)
        if raw is None:
            return None
        return [ToolDefinition.model_validate(t) for t in json.loads(raw)]

    async def set(self, tools: list[ToolDefinition]) -> None:
        payload = json.dumps([t.model_dump() for t in tools])
        await self.redis.set(self.KEY, payload, ex=self.TTL_SECONDS)

    async def invalidate(self) -> None:
        await self.redis.delete(self.KEY)
```

**Cache invalidation via pub/sub:**

1. Registry service publishes to `contextiq:tool_registry:changed` after every mutation (TASK-US002-02)
2. Gateway starts a background asyncio task that subscribes to `contextiq:tool_registry:changed`:
   ```python
   async def _subscribe_invalidation(redis: Redis, cache: ToolListCache):
       pubsub = redis.pubsub()
       await pubsub.subscribe("contextiq:tool_registry:changed")
       async for message in pubsub.listen():
           if message["type"] == "message":
               await cache.invalidate()
   ```
3. Subscriber task is started in FastAPI `lifespan` context and cancelled on shutdown

**Read-through pattern in `ToolRegistryService.get_active_tools()`:**
```python
async def get_active_tools(self) -> list[ToolDefinition]:
    cached = await self.cache.get()
    if cached is not None:
        return cached
    tools = await self.repo.find_active()
    await self.cache.set(tools)
    return tools
```

## Acceptance Criteria

- [ ] Cache hit: `tools/list` served in < 50 ms when cache is warm (measured via `pytest-benchmark`)
- [ ] Cache miss: database is queried and result is written to cache; subsequent call is a cache hit
- [ ] After a tool is registered or updated, `tools/list` reflects the change within ≤ 30 s (pub/sub invalidation)
- [ ] Cache TTL of 60 s acts as a fallback: stale cache is evicted within 60 s even if pub/sub fails
- [ ] If Redis is unavailable, the service falls back to direct DB query (no unhandled exception)
- [ ] Unit tests use `fakeredis.aioredis` to simulate cache hit, miss, and invalidation

## Dependencies

- TASK-US002-02 (pub/sub publish on mutation)
- EP-DATA-001 Redis HA (US-051)
- TASK-US001-01 (FastAPI lifespan for subscriber task)

## Definition of Done

- [ ] `ToolListCache` implemented and injected into `ToolRegistryService` via FastAPI `Depends`
- [ ] Pub/sub subscriber started in app lifespan with graceful shutdown
- [ ] Unit test coverage ≥ 90% for `cache/tool_cache.py` using `fakeredis`
- [ ] Integration test: register a tool via Admin API, confirm `tools/list` cache miss → warm → invalidated cycle
- [ ] Redis unavailability scenario tested: service falls back to DB without 500 error
