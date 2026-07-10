# TASK-US013-02 — `ContextCacheStore`: Redis Read/Write with Per-Source TTL

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US013-02 |
| User Story | US-013 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend / Caching |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `ContextCacheStore`, the async Redis adapter that serialises and deserialises `list[RetrievedChunk]` and enforces a configurable TTL per source type. A cache hit must return the deserialised chunk list within the 50 ms budget. The store is the low-level I/O layer; cache-aside orchestration lives in the wrapper (TASK-US013-03).

## Implementation Details

**Technology:** Python 3.11+, `redis.asyncio>=5.0`, `pydantic>=2.0`

**File locations:**
- `src/retrieval/cache/cache_store.py` — `ContextCacheStore` class and `TTL_CONFIG`
- `tests/retrieval/cache/test_cache_store.py` — tests with `fakeredis.aioredis`

**Per-source TTL configuration:**

```python
# src/retrieval/cache/cache_store.py
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk

# Default TTL by source type (seconds). Configurable via settings overlay.
TTL_CONFIG: dict[str, int] = {
    # Code sources — changes frequently during active development
    "github":      5 * 60,    # 5 minutes
    "gitlab":      5 * 60,

    # Documentation and wiki sources — updated less frequently
    "confluence": 30 * 60,    # 30 minutes
    "notion":     30 * 60,

    # Observability — metrics data is time-series; short TTL
    "grafana":     2 * 60,    # 2 minutes
    "datadog":     2 * 60,
    "pagerduty":   2 * 60,

    # Ticket trackers — moderate change rate
    "jira":       10 * 60,    # 10 minutes
    "stackoverflow": 60 * 60, # 60 minutes — external, rarely changes
}
DEFAULT_TTL: int = 10 * 60   # fallback for unregistered source types
```

**`ContextCacheStore`:**

```python
import json
from redis.asyncio import Redis
from src.retrieval.cache.cache_key import ContextCacheKey, redis_key

class ContextCacheStore:
    def __init__(self, redis: Redis, ttl_config: dict[str, int] = TTL_CONFIG) -> None:
        self._redis      = redis
        self._ttl_config = ttl_config

    async def get(self, key: ContextCacheKey) -> list[RetrievedChunk] | None:
        """Return cached chunks, or None on cache miss."""
        raw = await self._redis.get(redis_key(key))
        if raw is None:
            return None
        data = json.loads(raw)
        return [RetrievedChunk.model_validate(item) for item in data]

    async def set(
        self,
        key:    ContextCacheKey,
        chunks: list[RetrievedChunk],
    ) -> None:
        """Serialise and store chunks with the source-appropriate TTL."""
        ttl     = self._ttl_config.get(key.source_id, DEFAULT_TTL)
        payload = json.dumps([c.model_dump(mode="json") for c in chunks])
        await self._redis.set(redis_key(key), payload, ex=ttl)

    async def invalidate_source(self, source_id: str) -> int:
        """Delete all cache entries for a given source. Returns count deleted."""
        pattern = f"ctx_cache:{source_id}:*"
        deleted = 0
        async for key_bytes in self._redis.scan_iter(match=pattern, count=100):
            await self._redis.delete(key_bytes)
            deleted += 1
        return deleted
```

**Serialisation notes:**
- `model_dump(mode="json")` converts `datetime` and `Literal` fields to JSON-native types
- `RetrievedChunk.model_validate()` round-trips correctly because the model uses `ConfigDict(frozen=True)` with standard Pydantic v2 validators
- Payload is stored as a JSON string (not MessagePack or pickle) to keep it human-readable and Redis CLI-inspectable in staging

**50 ms cache-hit budget:**
- A `GET` on a Redis Cluster node over loopback typically completes in < 1 ms; JSON deserialisation of 20 chunks (~20 KB) adds < 5 ms
- The 50 ms budget is an end-to-end p99 budget from the caller's perspective — the store alone should not account for more than 10 ms

**`invalidate_source` safety:**
- `SCAN` with `count=100` is used instead of `KEYS` to avoid blocking the Redis event loop on large keyspaces
- Deletions are issued one key at a time to prevent `DEL` with many arguments from blocking

## Acceptance Criteria

- [ ] `store.get(key)` returns `None` for a key that has never been set
- [ ] `store.set(key, chunks)` followed by `store.get(key)` returns the original chunks (round-trip)
- [ ] `store.get()` deserialises within 50 ms for a payload of 20 `RetrievedChunk` instances (benchmarked with `fakeredis`)
- [ ] `store.set()` applies TTL from `TTL_CONFIG[source_id]`; a `github` entry expires in 300 s
- [ ] `store.set()` uses `DEFAULT_TTL` for an unregistered source type
- [ ] `store.invalidate_source("github")` deletes all `ctx_cache:github:*` keys and returns the count
- [ ] All tests use `fakeredis.aioredis` — no live Redis connection in CI

## Dependencies

- TASK-US013-01 (`ContextCacheKey`, `redis_key()`)
- TASK-US012-01 (`RetrievedChunk.model_dump()` and `model_validate()`)
- TASK-US005-03 (Redis connection pool — `Redis` instance shared with checkpointer via FastAPI app state)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 85% for `src/retrieval/cache/cache_store.py`
- [ ] `TTL_CONFIG` covers all source types defined in `SOURCE_MAP` (TASK-US009-03) — startup assertion validates this
- [ ] `KEYS` command is not used anywhere — only `SCAN` for bulk operations
- [ ] `mypy --strict` passes; no `ruff` lint errors
