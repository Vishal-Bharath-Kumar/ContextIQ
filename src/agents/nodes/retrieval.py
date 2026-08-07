"""retrieval_agent LangGraph node — parallel connector dispatch.

TASK-US007-01: retrieval_agent node with asyncio.gather parallel dispatch.

Reads ``execution_plan`` from ``AgentState``, resolves the active connectors
for every requested source, and dispatches all ``fetch()`` calls concurrently
via :class:`~src.agents.retrieval.parallel_dispatcher.ParallelConnectorDispatcher`.

``get_connector_registry()`` returns the module-level singleton registry, which
is injected at application startup via ``set_connector_registry()``.  Tests
call ``set_connector_registry()`` directly to inject a mock.
"""
from __future__ import annotations

import logging

from src.agents.config import settings
from src.agents.retrieval.aggregator import ContextAggregator
from src.agents.retrieval.parallel_dispatcher import ContextChunk, ParallelConnectorDispatcher
from src.agents.schemas.execution_plan import ExecutionPlan
from src.agents.state import AgentState, ExecutionStatus
from src.connector_sdk.registry import ConnectorRegistry
from src.gateway.tools.enterprise._local_tools import CODE_ROOTS, DOC_ROOT, search_workspace
from src.observability.tracing.node_span import otel_node_span
from src.retrieval.ranking.filters import count_tokens

_logger = logging.getLogger(__name__)

_CODE_RELATED_INTENTS: set[str] = {"debugging", "code-gen", "code-review"}
_CODE_FOCUSED_PHRASES: tuple[str, ...] = (
    "source code",
    "code file",
    "code files",
    "implementation",
    "class ",
    "function",
    "middleware",
    "router",
    "endpoint",
)
_CODE_FILE_SUFFIXES: tuple[str, ...] = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rb",
    ".kt", ".cs", ".cpp", ".c", ".h", ".hpp", ".rs", ".swift",
)

# ---------------------------------------------------------------------------
# Registry singleton — set by lifespan / test fixtures
# ---------------------------------------------------------------------------

_registry: ConnectorRegistry | None = None


def set_connector_registry(registry: ConnectorRegistry) -> None:
    """Inject the ``ConnectorRegistry`` singleton used by ``retrieval_node``.

    Must be called once during application startup (FastAPI lifespan) before
    the first agent request is processed.  In tests, call this in a fixture
    with a mock registry.
    """
    global _registry  # noqa: PLW0603
    _registry = registry


def get_connector_registry() -> ConnectorRegistry:
    """Return the active ``ConnectorRegistry`` singleton.

    Raises:
        RuntimeError: when ``set_connector_registry()`` has not been called.
    """
    if _registry is None:
        raise RuntimeError(
            "ConnectorRegistry has not been initialised. "
            "Call set_connector_registry() during application startup."
        )
    return _registry


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


@otel_node_span("retrieval.hybrid_search")
async def retrieval_node(state: AgentState) -> dict:
    """Dispatch connector fetches for all sources in ``execution_plan``.

    Reads:
        ``execution_plan``: :class:`~src.agents.schemas.execution_plan.ExecutionPlan`
        instance containing ``sources`` (list[str]) and
        ``token_budget_per_source`` (dict[str, int]).
        ``prompt``: raw user query forwarded to every connector.

    Returns:
        Partial state update with ``raw_context``, ``ranked_context``,
        ``current_node``, and ``status``.
    """
    plan: ExecutionPlan = state["execution_plan"]  # typed; KeyError if missing → pipeline_failed
    prompt: str = state["prompt"]

    # TASK-US038-04: inject per-request OTel context into each connector instance
    # so the @connector_span decorator can parent its child span to the root span.
    registry = get_connector_registry()
    otel_ctx = state.get("_otel_ctx")
    request_id = str(state.get("request_id", ""))
    source_ids = list(plan.sources)
    if settings.prefer_runtime_available_sources:
        available_sources = [src for src in source_ids if registry.get(src) is not None]
        if available_sources:
            source_ids = available_sources

    for src in source_ids:
        connector = registry.get(src)
        if connector is not None:
            connector._otel_ctx = otel_ctx
            connector._request_id = request_id

    dispatcher = ParallelConnectorDispatcher(
        connector_registry=get_connector_registry(),
    )

    results = await dispatcher.fetch_all(
        query=prompt,
        source_ids=source_ids,
        token_budget_per_source=plan.token_budget_per_source,
        intent_type=str(state.get("intent_type") or ""),
    )

    aggregator = ContextAggregator()
    aggregated = aggregator.aggregate(
        fetch_result=results,
        token_budget_per_source=plan.token_budget_per_source,
        global_token_budget=plan.token_budget_total,
    )
    if not aggregated.chunks:
        aggregated = _workspace_fallback_aggregate(
            prompt=prompt,
            intent_type=str(state.get("intent_type") or ""),
            plan=plan,
            degraded_sources=[d.model_dump() for d in aggregated.degraded_sources],
        )

    ranked_chunks = _rank_chunks_for_intent(
        aggregated.chunks,
        str(state.get("intent_type") or ""),
        prompt,
    )

    return {
        "raw_context": [c.model_dump() for c in aggregated.chunks],
        "ranked_context": [c.model_dump() for c in ranked_chunks],
        "degraded_sources": [d.model_dump() for d in aggregated.degraded_sources],
        "current_node": "retrieval_agent",
        "status": ExecutionStatus.RUNNING,
    }


def _workspace_fallback_aggregate(
    *,
    prompt: str,
    intent_type: str,
    plan: ExecutionPlan,
    degraded_sources: list[dict],
):
    limit = min(max(plan.token_budget_total // 500, 4), 12)
    matches = search_workspace(prompt, roots=CODE_ROOTS + [DOC_ROOT], limit=limit)
    chunks: list[ContextChunk] = []
    for index, match in enumerate(matches):
        snippet = str(match.get("snippet") or "")
        file_path = str(match.get("path") or f"workspace-{index}")
        chunks.append(
            ContextChunk(
                chunk_id=f"workspace:{file_path}:{match.get('line') or index}",
                source_id="workspace",
                content=snippet,
                token_count=max(1, count_tokens(snippet)),
                score=_normalise_workspace_score(match.get("score")),
                metadata={
                    "file_path": file_path,
                    "author": "workspace",
                    "last_modified": str(match.get("last_modified") or ""),
                    "source_url": file_path,
                    "title": str(match.get("title") or ""),
                    "intent_type": intent_type,
                },
            )
        )

    aggregated = ContextAggregator.AggregatedContext if False else None
    from src.agents.retrieval.aggregator import AggregatedContext, DegradedSource  # noqa: PLC0415

    degraded = [
        DegradedSource(
            source_id=str(item.get("source_id") or "unknown"),
            error_type=str(item.get("error_type") or "unknown"),
            message=str(item.get("message") or ""),
        )
        for item in degraded_sources
    ]
    if chunks:
        degraded.append(
            DegradedSource(
                source_id="workspace",
                error_type="LocalWorkspaceFallback",
                message="No connector results were available; used local workspace retrieval fallback.",
            )
        )

    return AggregatedContext(
        chunks=chunks,
        total_token_count=sum(chunk.token_count for chunk in chunks),
        source_count=len({chunk.source_id for chunk in chunks}),
        degraded_sources=degraded,
    )


def _normalise_workspace_score(raw_score: object) -> float:
    try:
        value = float(raw_score)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(round(value / 20.0, 4), 1.0))


def _rank_chunks_for_intent(chunks: list, intent_type: str, prompt: str) -> list:
    if intent_type not in _CODE_RELATED_INTENTS and not _looks_code_focused_prompt(prompt):
        return chunks

    def score(item: object) -> int:
        metadata = getattr(item, "metadata", {}) or {}
        file_path = str(metadata.get("file_path", "")).lower()
        value = 0
        if getattr(item, "source_id", "") == "github":
            value += 2
        if file_path.startswith("src/") or "/src/" in file_path:
            value += 4
        if file_path.endswith(_CODE_FILE_SUFFIXES):
            value += 5
        if file_path.endswith(".md") or file_path.endswith(".rst") or "/docs/" in file_path or file_path.startswith("docs/"):
            value -= 5
        if file_path.endswith("readme.md"):
            value -= 4
        return value

    indexed = list(enumerate(chunks))
    indexed.sort(key=lambda item: (-score(item[1]), item[0]))
    return [chunk for _idx, chunk in indexed]


def _looks_code_focused_prompt(prompt: str) -> bool:
    lowered = prompt.lower()
    return any(phrase in lowered for phrase in _CODE_FOCUSED_PHRASES)
