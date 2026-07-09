# TASK-US003-04 — Session Isolation for Concurrent Tool Calls

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US003-04 |
| User Story | US-003 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend / Concurrency |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Ensure that concurrent `tools/call` invocations from the same or different MCP sessions execute in fully isolated asyncio task contexts with no shared mutable state. Each call must receive independent execution state, correlation IDs, and log context without interfering with parallel calls.

## Implementation Details

**Technology:** Python 3.11+, `contextvars`, `asyncio`, `structlog` (or `logging` with context injection)

**File locations:**
- `src/gateway/context/request_context.py` — `RequestContext` dataclass + `ContextVar` definitions
- `src/gateway/middleware/context_middleware.py` — populates `RequestContext` from JWT + request
- `src/gateway/handlers/tools_call.py` — reads context from `ContextVar` (no argument threading)
- `tests/gateway/test_concurrent_tool_calls.py` — concurrency isolation tests

**`RequestContext` via `contextvars`:**

```python
from contextvars import ContextVar
from dataclasses import dataclass

@dataclass(frozen=True)
class RequestContext:
    request_id: str
    user_id: str
    session_id: str
    trace_id: int

# Module-level ContextVar — isolated per asyncio task automatically
_request_ctx: ContextVar[RequestContext] = ContextVar("request_context")

def get_request_context() -> RequestContext:
    return _request_ctx.get()

def set_request_context(ctx: RequestContext) -> Token:
    return _request_ctx.set(ctx)
```

`ContextVar` is natively isolated per asyncio task: when `asyncio.create_task()` or `asyncio.gather()` spawns child tasks, each inherits a **copy** of the context at spawn time — changes inside the child do not propagate back. FastMCP creates one asyncio task per handler invocation, so isolation is automatic.

**Middleware populates context before handler:**
```python
class RequestContextMiddleware:
    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            ctx = RequestContext(
                request_id=str(uuid4()),
                user_id=scope["state"]["user_id"],  # set by JWT middleware
                session_id=scope["state"]["session_id"],
                trace_id=trace.get_current_span().get_span_context().trace_id,
            )
            token = set_request_context(ctx)
            try:
                await self.app(scope, receive, send)
            finally:
                _request_ctx.reset(token)   # clean up after request
```

**Structured log binding** — bind `request_id` and `session_id` to every log record within the task:
```python
logger = structlog.get_logger().bind(
    request_id=ctx.request_id,
    session_id=ctx.session_id,
)
```

**No shared mutable state rules (enforced via code review checklist):**
- No module-level dicts/lists mutated during request handling
- No class-level instance variables shared across requests
- Agent Worker dispatch payload is constructed fresh per call (TASK-US003-01)

**Concurrency test pattern:**
```python
async def test_concurrent_calls_isolated():
    results = await asyncio.gather(
        call_tool("get_context", {"prompt": "call A"}),
        call_tool("get_context", {"prompt": "call B"}),
        call_tool("get_context", {"prompt": "call C"}),
    )
    # Assert each result contains its own request_id, not another call's
    request_ids = [r.request_id for r in results]
    assert len(set(request_ids)) == 3   # all distinct
```

## Acceptance Criteria

- [ ] 10 concurrent `tools/call` requests complete with distinct `request_id` values — no ID collisions (verified in concurrency test)
- [ ] A failure in one concurrent call (simulated timeout) does not affect the response of the other concurrent calls
- [ ] Log records for concurrent calls contain correct `request_id` binding — no cross-contamination (verified by capturing structured log output)
- [ ] `_request_ctx.reset(token)` is called in `finally` block — no stale context leaked after request completes
- [ ] `ContextVar` isolation confirmed: child task context changes do not propagate to parent (unit test using `asyncio.create_task`)

## Dependencies

- TASK-US003-01 (handler reads `RequestContext` from `ContextVar`)
- TASK-US001-04 (circuit-breaker is stateful but thread-safe via `pybreaker` — verify compatibility with asyncio)

## Definition of Done

- [ ] `contextvars`-based `RequestContext` implemented and injected into all handler call sites
- [ ] Concurrency test with 20 simultaneous calls passes with zero `request_id` collisions
- [ ] Log output from concurrent calls verified distinct via `caplog` fixture in pytest
- [ ] Code review checklist item "no shared mutable state in handler path" added to PR template
- [ ] `mypy --strict` passes on `context/request_context.py`
