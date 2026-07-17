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
from src.agents.retrieval.parallel_dispatcher import ParallelConnectorDispatcher
from src.agents.schemas.execution_plan import ExecutionPlan
from src.agents.state import AgentState, ExecutionStatus
from src.connector_sdk.registry import ConnectorRegistry
from src.observability.tracing.node_span import otel_node_span

_logger = logging.getLogger(__name__)

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
    for src in plan.sources:
        connector = registry.get(src)
        if connector is not None:
            connector._otel_ctx = otel_ctx
            connector._request_id = request_id

    dispatcher = ParallelConnectorDispatcher(
        connector_registry=get_connector_registry(),
        timeout_seconds=settings.connector_timeout_seconds,
    )

    results = await dispatcher.fetch_all(
        query=prompt,
        source_ids=plan.sources,
        token_budget_per_source=plan.token_budget_per_source,
    )

    aggregator = ContextAggregator()
    aggregated = aggregator.aggregate(
        fetch_result=results,
        token_budget_per_source=plan.token_budget_per_source,
        global_token_budget=plan.token_budget_total,
    )

    return {
        "raw_context": [c.model_dump() for c in aggregated.chunks],
        "ranked_context": [c.model_dump() for c in aggregated.chunks],  # ranking in EP-004
        "degraded_sources": [d.model_dump() for d in aggregated.degraded_sources],
        "current_node": "retrieval_agent",
        "status": ExecutionStatus.RUNNING,
    }
