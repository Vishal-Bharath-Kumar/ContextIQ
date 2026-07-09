# TASK-US005-03 — Wire LangGraph AsyncRedisSaver Checkpointer for State Persistence

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US005-03 |
| User Story | US-005 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend / Caching |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Configure LangGraph's `AsyncRedisSaver` checkpointer so that `AgentState` is persisted to Redis after every node transition, enabling mid-flight state recovery if the Agent Worker pod restarts. Apply a 1-hour TTL to prevent unbounded Redis growth.

## Implementation Details

**Technology:** Python 3.11+, `langgraph`, `langgraph-checkpoint-redis` (or `langgraph[redis]`), `redis.asyncio`

**File locations:**
- `src/agents/checkpointer.py` — `get_redis_checkpointer()` factory and TTL wrapper
- `src/agents/graph.py` — `build_graph()` receives checkpointer from factory (extends TASK-US005-01)
- `tests/agents/test_checkpointer.py` — tests with `fakeredis`

**Checkpointer setup:**
```python
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

async def get_redis_checkpointer() -> AsyncRedisSaver:
    redis_url = settings.redis_url   # e.g. redis://redis-sentinel:26379/0
    checkpointer = AsyncRedisSaver.from_conn_string(redis_url)
    await checkpointer.setup()       # creates required Redis key structures
    return checkpointer
```

**1-hour TTL enforcement:**
LangGraph's `AsyncRedisSaver` writes checkpoint keys. Wrap the saver to set TTL on every write:
```python
class TTLRedisSaver(AsyncRedisSaver):
    TTL_SECONDS: int = 3600

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        result = await super().aput(config, checkpoint, metadata, new_versions)
        # Apply TTL to the checkpoint key after write
        thread_id = config["configurable"]["thread_id"]
        key = f"checkpoint:{thread_id}"
        await self.conn.expire(key, self.TTL_SECONDS)
        return result
```

**Redis key namespace:**
```
checkpoint:<request_id>           → latest AgentState snapshot (JSON)
checkpoint:<request_id>:metadata  → node history, timestamps
checkpoint:<request_id>:writes    → pending writes buffer
```
All keys share the same `request_id` prefix and inherit the 1-hour TTL.

**Checkpointer as application singleton:** Initialized once during FastAPI lifespan:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpointer = await get_redis_checkpointer()
    app.state.checkpointer = checkpointer
    yield
    await checkpointer.conn.aclose()
```

**Recovery scenario:** If the Agent Worker pod restarts mid-flight, the next request with the same `thread_id` (same `request_id`) can resume from the last checkpoint:
```python
# Resume from last saved node instead of re-running from scratch
state = await graph.aget_state(config={"configurable": {"thread_id": request_id}})
if state and state.values.get("status") not in ("complete", "failed"):
    final_state = await graph.ainvoke(None, config=config)  # resume
```

## Acceptance Criteria

- [ ] After a graph node executes, `AgentState` is readable from Redis using `graph.aget_state(config)`
- [ ] Redis checkpoint keys have a TTL of exactly 3 600 s (verified via `redis.ttl(key)` in test)
- [ ] A graph invocation interrupted mid-flight (simulated by raising an exception inside a node) can be inspected via `graph.aget_state()` — last good state is available
- [ ] Checkpointer initialization failure (Redis unreachable) surfaces as a startup error, not a silent failure
- [ ] Unit tests use `fakeredis.aioredis` to verify: write → TTL set, read → correct state, TTL expiry → key gone

## Dependencies

- TASK-US005-01 (`build_graph()` receives checkpointer as parameter)
- EP-DATA-001 Redis HA (US-051)
- `langgraph-checkpoint-redis` or equivalent added to `pyproject.toml`

## Definition of Done

- [ ] `TTLRedisSaver` wrapping `AsyncRedisSaver` implemented and injected into `build_graph()`
- [ ] Integration test: complete graph invocation → verify all 5 checkpoint keys present in Redis → TTL = 3600 ± 5 s
- [ ] Recovery test: agent worker restarted after node 2 → next call resumes from node 3 (verified by node execution counter)
- [ ] `REDIS_URL` documented in `.env.example`; Vault dynamic credential injection path documented
