"""Compression node for the ContextIQ pipeline.

Runs three stages in order:
1. Rule-based exact deduplication and boilerplate removal.
2. Semantic near-duplicate consolidation.
3. Optional chunk summarisation for over-threshold chunks.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast
import uuid

from src.compression.rule_based_compressor import RuleBasedCompressor
from src.compression.semantic.semantic_deduplicator import SemanticDeduplicator
from src.compression.summarization.chunk_summarizer import ChunkSummarizer
from src.retrieval.ranking.filters import count_tokens
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

from src.agents.state import AgentState, ExecutionStatus
from src.observability.tracing.node_span import otel_node_span

logger = logging.getLogger(__name__)

_compressor = RuleBasedCompressor()
_semantic_dedup: SemanticDeduplicator | None = None


@otel_node_span("compression.context_window")
async def compression_node(state: AgentState) -> AgentState:
    raw_ranked_context = list(state.get("ranked_context") or [])
    pre_compression_context = [
        _serialise_chunk(chunk) for chunk in raw_ranked_context
    ]
    normalised_chunks = [
        _coerce_to_retrieved_chunk(chunk, idx)
        for idx, chunk in enumerate(raw_ranked_context)
    ]

    if not normalised_chunks:
        tokens_before = 0
        tokens_after = 0
        compressed_output: list[RetrievedChunk] = []
        removed_chunks = []
        consolidated_sources = None
    else:
        after_rules, rule_removed = _compressor.compress(normalised_chunks)
        after_semantic, semantic_removed, consolidated = _get_semantic_dedup().deduplicate(after_rules)
        compressed_output = await _summarize_chunks(after_semantic, state)

        removed_chunks = rule_removed + semantic_removed
        consolidated_sources = consolidated or None
        tokens_before = _count_chunk_tokens(normalised_chunks)
        tokens_after = _count_chunk_tokens(compressed_output)

    jwt_claims: dict[str, Any] = state.get("jwt_claims") or {}
    groups: list[str] = jwt_claims.get("groups") or ["default"]
    recorder = _get_compression_recorder(state)
    if recorder is not None:
        comp_rec = _build_compression_record(
            state=state,
            jwt_claims=jwt_claims,
            groups=groups,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )
        if comp_rec is not None:
            recorder.record(comp_rec)
    else:
        logger.warning("compression_recorder not configured; skipping compression metrics")

    return {
        "compressed_context": compressed_output,
        "ranked_context": compressed_output,
        "removed_chunks": removed_chunks,
        "consolidated_sources": consolidated_sources,
        "tokens_before_compression": tokens_before,
        "tokens_after_compression": tokens_after,
        "current_node": "compression_agent",
        "status": ExecutionStatus.RUNNING,
        "ranked_context_pre_compression": pre_compression_context,
        "compression_tokens_before": tokens_before,
        "compression_tokens_after": tokens_after,
    }


# ------------------------------------------------------------------ #
# Injectable singletons (set during lifespan startup)                 #
# ------------------------------------------------------------------ #

_DEFAULT_COMPRESSION_RECORDER: Any | None = None


def set_compression_recorder(recorder: Any) -> None:
    global _DEFAULT_COMPRESSION_RECORDER
    _DEFAULT_COMPRESSION_RECORDER = recorder


def _get_semantic_dedup() -> SemanticDeduplicator:
    global _semantic_dedup
    if _semantic_dedup is None:
        _semantic_dedup = SemanticDeduplicator()
    return _semantic_dedup


def _get_compression_recorder(state: AgentState) -> Any | None:
    config: dict[str, Any] = cast(dict[str, Any], state.get("_config") or {})
    return config.get("compression_recorder") or _DEFAULT_COMPRESSION_RECORDER


def _get_request_id(state: AgentState) -> uuid.UUID:
    raw = state.get("request_id")
    if isinstance(raw, uuid.UUID):
        return raw
    if isinstance(raw, str):
        return uuid.UUID(raw)
    return uuid.uuid4()


def _build_langfuse_callbacks(state: AgentState) -> list[object]:
    handler = make_langfuse_handler(
        request_id=str(state.get("request_id") or ""),
        user_id=str(state.get("user_id") or "anonymous"),
        session_id=str(state.get("request_id") or ""),
    )
    return [handler] if handler is not None else []


def _coerce_to_retrieved_chunk(item: object, index: int) -> RetrievedChunk:
    if isinstance(item, RetrievedChunk):
        return item

    if not isinstance(item, dict):
        raise TypeError(f"Unsupported ranked_context item type: {type(item).__name__}")

    metadata_raw = item.get("metadata")
    metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
    timestamp = _coerce_timestamp(metadata.get("timestamp"))
    source_id = str(item.get("source_id") or item.get("source") or "unknown")
    chunk_id = str(item.get("chunk_id") or item.get("entity_id") or f"{source_id}:{index}")
    content = _extract_chunk_content(item)

    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        content=content,
        score=float(item.get("score") or 0.0),
        metadata=ChunkMetadata(
            file_path=str(metadata.get("file_path") or item.get("name") or f"{source_id}/{chunk_id}"),
            timestamp=timestamp,
            author=str(metadata.get("author") or "unknown"),
            url=str(metadata.get("url")) if metadata.get("url") else None,
            chunk_index=_safe_int(metadata.get("chunk_index")),
        ),
        search_mode=str(item.get("search_mode") or "rrf"),
        vector_score=_safe_float(item.get("vector_score")),
        keyword_score=_safe_float(item.get("keyword_score")),
    )


def _extract_chunk_content(item: dict[str, object]) -> str:
    content = item.get("content") or item.get("text") or item.get("path_summary")
    if content:
        return str(content)

    name = item.get("name")
    entity_type = item.get("entity_type")
    properties = item.get("properties")
    if name or entity_type or properties:
        return " ".join(
            str(part)
            for part in [name, entity_type, properties]
            if part not in (None, "")
        )
    return ""


def _coerce_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(tz=UTC)
    return datetime.now(tz=UTC)


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _count_chunk_tokens(chunks: list[RetrievedChunk]) -> int:
    return sum(count_tokens(chunk.content) for chunk in chunks)


def _serialise_chunk(chunk: object) -> dict[str, object]:
    if isinstance(chunk, RetrievedChunk):
        return chunk.model_dump()
    if isinstance(chunk, dict):
        return chunk
    raise TypeError(f"Unsupported chunk type for serialisation: {type(chunk).__name__}")


async def _summarize_chunks(
    chunks: list[RetrievedChunk],
    state: AgentState,
) -> list[RetrievedChunk]:
    if not chunks:
        return []

    try:
        callbacks = _build_langfuse_callbacks(state)
        summarizer = ChunkSummarizer(callbacks=callbacks)
    except Exception:
        return chunks

    try:
        return await summarizer.summarize(chunks)
    except Exception:
        return chunks


def make_langfuse_handler(
    request_id: str,
    user_id: str,
    session_id: str,
) -> object | None:
    try:
        from src.compression.summarization.langfuse_handler import make_langfuse_handler as factory
    except ModuleNotFoundError:
        return None

    return factory(request_id=request_id, user_id=user_id, session_id=session_id)


def _build_compression_record(
    state: AgentState,
    jwt_claims: dict[str, Any],
    groups: list[str],
    tokens_before: int,
    tokens_after: int,
) -> object | None:
    try:
        from src.observability.cost.schemas import CompressionRecord
    except ModuleNotFoundError:
        return None

    return CompressionRecord(
        request_id=_get_request_id(state),
        tenant_id=state.get("tenant_id") or "default",
        user_id=jwt_claims.get("sub") or "anonymous",
        team_id=jwt_claims.get("team_id") or groups[0],
        intent_type=str(state.get("intent_type") or "unknown"),
        timestamp=datetime.now(tz=UTC),
        tokens_before_compression=tokens_before,
        tokens_after_compression=tokens_after,
    )
