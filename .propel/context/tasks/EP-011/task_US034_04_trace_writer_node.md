# TASK-US034-04 — `trace_writer_node` + Async Background Dispatch

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US034-04 |
| User Story | US-034 |
| Epic | EP-011 — AI Execution Replay |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the `trace_writer_node()` LangGraph terminal node that assembles an `ExecutionTrace` from the completed `AgentState`, then dispatches both the MinIO write and the PostgreSQL index upsert as a non-blocking `asyncio.create_task()` background coroutine (AC-6). The main request path returns to the caller immediately after `trace_writer_node` returns — the write completes in the background. Also defines `AgentState` extensions (`trace_id`, `trace_object_key`) and the background task function `_persist_trace()`.

## Implementation Details

**Technology:** Python 3.11+, LangGraph `>=0.2.0`, `asyncio`, OpenTelemetry, Langfuse `>=2.0`

**File locations:**
- `src/audit/trace/writer_node.py` — `trace_writer_node()`, `_persist_trace()`, `_assemble_trace()`
- `src/agents/state.py` — extend `AgentState` TypedDict
- `src/agents/graph.py` — register as terminal node
- `tests/audit/test_trace_writer_node.py`

---

### `AgentState` extensions

```python
# src/agents/state.py  (extend existing TypedDict — do NOT replace)
# Add these fields to the existing AgentState TypedDict:

    trace_id:         str | None          # str(UUID) set at pipeline entry
    trace_object_key: str | None          # populated by trace_writer_node after dispatch
    trace_written:    bool                # True once _persist_trace task is enqueued
```

---

### `trace_writer_node()`

```python
# src/audit/trace/writer_node.py
from __future__ import annotations
import asyncio
import logging
import uuid
from datetime  import datetime, timezone

from opentelemetry import trace
from langfuse      import Langfuse

from src.agents.state              import AgentState
from src.audit.trace.schemas       import (
    ExecutionTrace, TraceIndexEntry, ExecutionPlanStep,
    RetrievedChunkSummary, CompressionDelta, GovernanceDecisionSummary,
)
from src.audit.trace.object_store  import TraceObjectStore
from src.audit.trace.repository    import TraceIndexRepository

logger   = logging.getLogger(__name__)
tracer   = trace.get_tracer(__name__)
langfuse = Langfuse()


async def trace_writer_node(state: AgentState) -> AgentState:
    """
    LangGraph terminal node — Execution Trace Writer.

    Position: final node in the pipeline, after the model response is received.

    Responsibilities:
    1. Assemble an ExecutionTrace from AgentState (AC-2 field mapping).
    2. Dispatch _persist_trace() as asyncio.create_task() — fire-and-forget (AC-6).
    3. Return the updated state immediately (zero latency added to main path).

    The background task _persist_trace() writes to MinIO (AC-1) and
    upserts the PostgreSQL index (AC-4).
    """
    with tracer.start_as_current_span("audit.trace_writer") as span:
        trace_obj = _assemble_trace(state)
        span.set_attribute("trace.request_id", str(trace_obj.request_id))
        span.set_attribute("trace.intent",     trace_obj.intent)

        # AC-6: dispatch asynchronously — do NOT await
        asyncio.create_task(
            _persist_trace(trace_obj, state),
            name=f"persist_trace_{trace_obj.request_id}",
        )

        langfuse.create_event(
            name     = "trace_writer_dispatched",
            input    = {"request_id": str(trace_obj.request_id)},
            metadata = {"intent": trace_obj.intent},
        )

        # Object key is available synchronously (computed locally, not from MinIO)
        from src.audit.trace.object_store import _build_key
        estimated_key = _build_key(trace_obj)

        return {
            **state,
            "trace_id":         str(trace_obj.request_id),
            "trace_object_key": estimated_key,
            "trace_written":    True,
        }


# ------------------------------------------------------------------ #
# Background task — runs after the HTTP response is already returned  #
# ------------------------------------------------------------------ #

async def _persist_trace(trace_obj: ExecutionTrace, state: AgentState) -> None:
    """
    Background coroutine: writes trace to MinIO (AC-1) and upserts PostgreSQL (AC-4).
    Errors are logged but never propagate — a trace write failure must never
    cause the response to fail (AC-6 principle: no latency impact).
    """
    object_store: TraceObjectStore      = _get_object_store(state)
    session_factory                     = _get_session_factory(state)

    try:
        # Step 1: Write to MinIO (AC-1, AC-3)
        result = await object_store.write(trace_obj)

        # Step 2: Upsert PostgreSQL index (AC-4)
        index_entry = TraceIndexEntry(
            request_id         = trace_obj.request_id,
            tenant_id          = trace_obj.tenant_id,
            user_id            = trace_obj.user_id,
            timestamp          = trace_obj.timestamp,
            intent             = trace_obj.intent,
            model_selected     = trace_obj.model_selected,
            governance_blocked = trace_obj.governance_decisions.governance_blocked,
            opa_denied_count   = trace_obj.governance_decisions.opa_denied_count,
            object_key         = result.object_key,
            object_version     = result.version_id,
        )
        async with session_factory() as session:
            repo = TraceIndexRepository(session)
            await repo.upsert(index_entry)
            await session.commit()

        logger.info(
            "trace.persisted request_id=%s key=%s version=%s",
            trace_obj.request_id, result.object_key, result.version_id,
        )
    except Exception:  # noqa: BLE001
        # Never raise — background task failure must not affect the main path (AC-6)
        logger.exception(
            "trace.persist_failed request_id=%s", trace_obj.request_id
        )


# ------------------------------------------------------------------ #
# Trace assembly from AgentState (AC-2 field mapping)                 #
# ------------------------------------------------------------------ #

def _assemble_trace(state: AgentState) -> ExecutionTrace:
    """Map all required AC-2 fields from AgentState into an ExecutionTrace."""
    request_id = _get_request_id(state)
    jwt_claims: dict  = state.get("jwt_claims") or {}
    user_id:    str   = jwt_claims.get("sub") or "anonymous"

    # retrieved_chunks pre-compression = full ranked_context before compression node
    pre_chunks  = _map_chunks(state.get("ranked_context_pre_compression") or [])
    # retrieved_chunks post-compression = ranked_context after compression node
    post_chunks = _map_chunks(state.get("ranked_context") or [])

    # Compression delta
    delta: CompressionDelta | None = None
    if state.get("compression_tokens_before") is not None:
        delta = CompressionDelta(
            tokens_before = state.get("compression_tokens_before", 0),
            tokens_after  = state.get("compression_tokens_after",  0),
            chunks_before = len(pre_chunks),
            chunks_after  = len(post_chunks),
        )

    # execution_plan from execution_trace list already in AgentState
    plan_steps = [
        ExecutionPlanStep(
            node     = entry.get("node") or "unknown",
            eval_ms  = entry.get("eval_ms"),
            metadata = {k: v for k, v in entry.items()
                        if k not in ("node", "eval_ms")},
        )
        for entry in (state.get("execution_trace") or [])
    ]

    governance = GovernanceDecisionSummary(
        findings_count      = len(state.get("governance_findings") or []),
        redacted_count      = sum(
            1 for f in (state.get("governance_findings") or [])
            if (f if isinstance(f, dict) else vars(f)).get("redacted", False)
        ),
        opa_denied_count    = state.get("opa_denied_count") or 0,
        opa_bundle_version  = state.get("opa_bundle_version") or "unknown",
        governance_blocked  = bool(state.get("governance_blocked")),
    )

    # Truncate response to max 500 chars for summary (avoid storing full LLM output in PG index)
    raw_response: str = state.get("response") or ""
    response_summary  = raw_response[:500] if raw_response else None

    return ExecutionTrace(
        request_id                       = request_id,
        tenant_id                        = state.get("tenant_id") or "default",
        user_id                          = user_id,
        timestamp                        = datetime.now(tz=timezone.utc),
        latency_ms                       = state.get("total_latency_ms"),
        prompt                           = state.get("query") or "",
        intent                           = state.get("intent") or "unknown",
        execution_plan                   = plan_steps,
        retrieved_chunks_pre_compression = pre_chunks,
        retrieved_chunks_post_compression= post_chunks,
        compression_delta                = delta,
        governance_decisions             = governance,
        model_selected                   = state.get("model_selected"),
        prompt_tokens                    = state.get("prompt_tokens"),
        completion_tokens                = state.get("completion_tokens"),
        response_summary                 = response_summary,
    )


def _map_chunks(chunks: list[dict]) -> list[RetrievedChunkSummary]:
    result = []
    for c in chunks:
        meta = c.get("metadata") or {}
        result.append(RetrievedChunkSummary(
            chunk_id             = str(c.get("chunk_id") or c.get("id") or ""),
            source_id            = str(c.get("source_id") or ""),
            relevance_score      = float(c.get("score") or c.get("relevance_score") or 0.0),
            classification_label = meta.get("classification_label", "internal"),
            redacted             = bool(c.get("redacted")),
            opa_denied           = bool(c.get("opa_denied")),
        ))
    return result


def _get_request_id(state: AgentState) -> uuid.UUID:
    raw = state.get("request_id")
    if isinstance(raw, uuid.UUID):
        return raw
    if isinstance(raw, str):
        return uuid.UUID(raw)
    return uuid.uuid4()


# ------------------------------------------------------------------ #
# Injectable singletons (set during lifespan startup)                 #
# ------------------------------------------------------------------ #

_DEFAULT_OBJECT_STORE:   TraceObjectStore | None = None
_DEFAULT_SESSION_FACTORY = None


def set_trace_object_store(store: TraceObjectStore) -> None:
    global _DEFAULT_OBJECT_STORE
    _DEFAULT_OBJECT_STORE = store


def set_trace_session_factory(factory) -> None:
    global _DEFAULT_SESSION_FACTORY
    _DEFAULT_SESSION_FACTORY = factory


def _get_object_store(state: AgentState) -> TraceObjectStore:
    config = state.get("_config") or {}
    return config.get("trace_object_store") or _DEFAULT_OBJECT_STORE


def _get_session_factory(state: AgentState):
    config = state.get("_config") or {}
    return config.get("trace_session_factory") or _DEFAULT_SESSION_FACTORY
```

---

### `StateGraph` registration

```python
# src/agents/graph.py — extend only; do NOT replace existing code
from src.audit.trace.writer_node import trace_writer_node

# Position: after the model response node, as the terminal node
graph.add_node("trace_writer",  trace_writer_node)
graph.add_edge("model_response", "trace_writer")
graph.set_finish_point("trace_writer")
```

---

### `ranked_context_pre_compression` state field

The compression node (upstream) must save the pre-compression context before modifying `ranked_context`:

```python
# src/agents/nodes/compression_node.py — extend only
# At the top of the compression node, before any truncation:
pre_compression_context = list(state.get("ranked_context") or [])

# … perform compression …

return {
    **state,
    "ranked_context":                   compressed_chunks,
    "ranked_context_pre_compression":   pre_compression_context,   # NEW — for trace AC-2
    "compression_tokens_before":        tokens_before,             # NEW
    "compression_tokens_after":         tokens_after,              # NEW
}
```

## Acceptance Criteria

- [ ] `trace_writer_node` returns the updated state and a dispatched background task within < 5 ms (confirmed by unit test timing)
- [ ] `_assemble_trace()` maps all 10 AC-2 fields from `AgentState` to `ExecutionTrace`
- [ ] `_persist_trace()` calls `object_store.write()` then `repo.upsert()` in sequence
- [ ] An exception in `_persist_trace()` is caught and logged — it does NOT propagate (AC-6)
- [ ] `trace_written` is `True` in the returned state once the task is enqueued
- [ ] `set_trace_object_store()` and `set_trace_session_factory()` allow test injection without a live MinIO or PostgreSQL

## Dependencies

- TASK-US034-01 (`ExecutionTrace`, `TraceIndexEntry`, sub-schemas)
- TASK-US034-02 (`TraceObjectStore`, `_build_key`)
- TASK-US034-03 (`TraceIndexRepository`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
