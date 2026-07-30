"""LangGraph terminal node for execution trace writing — TASK-US034-04.

Assembles an ExecutionTrace from the completed AgentState, then dispatches
MinIO write + PostgreSQL index upsert as a fire-and-forget asyncio background
task (AC-6).  The main request path returns immediately.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from opentelemetry import trace

from src.agents.state import AgentState
from src.audit.trace.object_store import TraceObjectStore, _build_key
from src.audit.trace.repository import TraceIndexRepository
from src.audit.trace.schemas import (
    CompressionDelta,
    ExecutionPlanStep,
    ExecutionTrace,
    GovernanceDecisionSummary,
    RetrievedChunkSummary,
    TraceIndexEntry,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
langfuse = None


def _get_langfuse() -> object | None:
    global langfuse
    if langfuse is not None:
        return langfuse
    try:
        from langfuse import Langfuse  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        logger.warning("trace_writer_node: Langfuse unavailable: %s", exc)
        return None
    try:
        langfuse = Langfuse()
    except Exception as exc:  # noqa: BLE001
        logger.warning("trace_writer_node: Langfuse init failed: %s", exc)
        return None
    return langfuse


# ------------------------------------------------------------------ #
# Terminal node                                                        #
# ------------------------------------------------------------------ #


async def trace_writer_node(state: AgentState) -> AgentState:
    """LangGraph terminal node — Execution Trace Writer.

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
        span.set_attribute("trace.intent", trace_obj.intent)

        # AC-6: dispatch asynchronously — do NOT await
        asyncio.create_task(
            _persist_trace(trace_obj, state),
            name=f"persist_trace_{trace_obj.request_id}",
        )

        lf = _get_langfuse()
        if lf is not None:
            lf.create_event(
                name="trace_writer_dispatched",
                input={"request_id": str(trace_obj.request_id)},
                metadata={"intent": trace_obj.intent},
            )

        # Object key is computed locally without hitting MinIO
        estimated_key = _build_key(trace_obj)

        return {
            **state,
            "trace_id": str(trace_obj.request_id),
            "trace_object_key": estimated_key,
            "trace_written": True,
        }


# ------------------------------------------------------------------ #
# Background task — runs after the HTTP response is already returned  #
# ------------------------------------------------------------------ #


async def _persist_trace(trace_obj: ExecutionTrace, state: AgentState) -> None:
    """Background coroutine: writes trace to MinIO (AC-1) and upserts PostgreSQL (AC-4).

    Errors are logged but never propagate — a trace write failure must never
    cause the response to fail (AC-6 principle: no latency impact).
    """
    object_store: TraceObjectStore = _get_object_store(state)
    session_factory = _get_session_factory(state)

    try:
        # Step 1: Write to MinIO (AC-1, AC-3)
        result = await object_store.write(trace_obj)

        # Step 2: Upsert PostgreSQL index (AC-4)
        index_entry = TraceIndexEntry(
            request_id=trace_obj.request_id,
            tenant_id=trace_obj.tenant_id,
            user_id=trace_obj.user_id,
            timestamp=trace_obj.timestamp,
            intent=trace_obj.intent,
            model_selected=trace_obj.model_selected,
            governance_blocked=trace_obj.governance_decisions.governance_blocked,
            opa_denied_count=trace_obj.governance_decisions.opa_denied_count,
            object_key=result.object_key,
            object_version=result.version_id,
        )
        async with session_factory() as session:
            repo = TraceIndexRepository(session)
            await repo.upsert(index_entry)
            await session.commit()

        logger.info(
            "trace.persisted request_id=%s key=%s version=%s",
            trace_obj.request_id,
            result.object_key,
            result.version_id,
        )
    except Exception:  # noqa: BLE001
        # Never raise — background task failure must not affect the main path (AC-6)
        logger.exception("trace.persist_failed request_id=%s", trace_obj.request_id)


# ------------------------------------------------------------------ #
# Trace assembly from AgentState (AC-2 field mapping)                 #
# ------------------------------------------------------------------ #


def _assemble_trace(state: AgentState) -> ExecutionTrace:
    """Map all required AC-2 fields from AgentState into an ExecutionTrace."""
    # Cast to dict[str, Any] to handle dynamic fields not declared in the TypedDict
    s: dict[str, Any] = cast(dict[str, Any], state)
    request_id = _get_request_id(state)
    jwt_claims: dict[str, Any] = s.get("jwt_claims") or {}
    user_id: str = str(jwt_claims.get("sub") or "anonymous")

    # retrieved_chunks pre-compression = full ranked_context before compression node
    pre_chunks = _map_chunks(s.get("ranked_context_pre_compression") or [])
    # retrieved_chunks post-compression = ranked_context after compression node
    post_chunks = _map_chunks(s.get("ranked_context") or [])

    # Compression delta
    delta: CompressionDelta | None = None
    if s.get("compression_tokens_before") is not None:
        delta = CompressionDelta(
            tokens_before=s.get("compression_tokens_before", 0),
            tokens_after=s.get("compression_tokens_after", 0),
            chunks_before=len(pre_chunks),
            chunks_after=len(post_chunks),
        )

    # execution_plan from execution_trace list already in AgentState
    plan_steps = [
        ExecutionPlanStep(
            node=entry.get("node") or "unknown",
            eval_ms=entry.get("eval_ms"),
            metadata={k: v for k, v in entry.items() if k not in ("node", "eval_ms")},
        )
        for entry in (s.get("execution_trace") or [])
    ]

    governance = GovernanceDecisionSummary(
        findings_count=len(s.get("governance_findings") or []),
        redacted_count=sum(
            1
            for f in (s.get("governance_findings") or [])
            if (f if isinstance(f, dict) else vars(f)).get("redacted", False)
        ),
        opa_denied_count=s.get("opa_denied_count") or 0,
        opa_bundle_version=s.get("opa_bundle_version") or "unknown",
        governance_blocked=bool(s.get("governance_blocked")),
    )

    # Truncate response to max 500 chars for summary (avoids storing full LLM output in PG index)
    raw_response: str = str(s.get("response") or "")
    response_summary = raw_response[:500] if raw_response else None

    return ExecutionTrace(
        request_id=request_id,
        tenant_id=s.get("tenant_id") or "default",
        user_id=user_id,
        timestamp=datetime.now(tz=UTC),
        latency_ms=s.get("total_latency_ms"),
        prompt=s.get("query") or "",
        intent=s.get("intent") or "unknown",
        execution_plan=plan_steps,
        retrieved_chunks_pre_compression=pre_chunks,
        retrieved_chunks_post_compression=post_chunks,
        compression_delta=delta,
        governance_decisions=governance,
        model_selected=s.get("model_selected"),
        prompt_tokens=s.get("prompt_tokens"),
        completion_tokens=s.get("completion_tokens"),
        response_summary=response_summary,
    )


def _map_chunks(chunks: list[dict[str, Any]]) -> list[RetrievedChunkSummary]:
    result = []
    for c in chunks:
        meta = c.get("metadata") or {}
        result.append(
            RetrievedChunkSummary(
                chunk_id=str(c.get("chunk_id") or c.get("id") or ""),
                source_id=str(c.get("source_id") or ""),
                relevance_score=float(c.get("score") or c.get("relevance_score") or 0.0),
                classification_label=meta.get("classification_label", "internal"),
                redacted=bool(c.get("redacted")),
                opa_denied=bool(c.get("opa_denied")),
            )
        )
    return result


def _get_request_id(state: AgentState) -> uuid.UUID:
    raw = state.get("request_id")
    if isinstance(raw, uuid.UUID):
        return raw
    if isinstance(raw, str):
        try:
            return uuid.UUID(raw)
        except ValueError:
            return uuid.uuid5(uuid.NAMESPACE_URL, raw)
    return uuid.uuid4()


# ------------------------------------------------------------------ #
# Injectable singletons (set during lifespan startup)                 #
# ------------------------------------------------------------------ #

_DEFAULT_OBJECT_STORE: TraceObjectStore | None = None
_DEFAULT_SESSION_FACTORY: Any = None


def set_trace_object_store(store: TraceObjectStore) -> None:
    global _DEFAULT_OBJECT_STORE
    _DEFAULT_OBJECT_STORE = store


def set_trace_session_factory(factory: Any) -> None:  # noqa: ANN401
    global _DEFAULT_SESSION_FACTORY
    _DEFAULT_SESSION_FACTORY = factory


def _get_object_store(state: AgentState) -> TraceObjectStore:
    config: dict[str, Any] = cast(dict[str, Any], state.get("_config") or {})
    return cast(TraceObjectStore, config.get("trace_object_store") or _DEFAULT_OBJECT_STORE)


def _get_session_factory(state: AgentState) -> Any:  # noqa: ANN401
    config: dict[str, Any] = cast(dict[str, Any], state.get("_config") or {})
    return config.get("trace_session_factory") or _DEFAULT_SESSION_FACTORY
