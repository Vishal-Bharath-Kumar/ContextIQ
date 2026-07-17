"""LangGraph node for Knowledge Graph context expansion — TASK-US029-04.

Wires EntityLinker → GraphTraversalClient → ranked_context append.
Satisfies AC-1 (Cypher traversal from ranked context), AC-4 (results appended
with source='knowledge_graph'), and AC-6 (token budget guard from execution plan).
"""
from __future__ import annotations

import logging

from langfuse import Langfuse
from opentelemetry import trace

from src.agents.state import AgentState
from src.knowledge_graph.schemas.edge import EdgeType
from src.knowledge_graph.traversal.entity_linker import EntityLinker
from src.knowledge_graph.traversal.neo4j_traversal_client import GraphTraversalClient
from src.knowledge_graph.traversal.schemas import TraversalConfig, TraversalSettings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
langfuse = Langfuse()


async def knowledge_graph_node(state: AgentState) -> AgentState:
    """LangGraph node — Knowledge Graph context expansion.

    Execution steps:
    1. Check remaining token budget from execution_plan; skip if zero.
    2. Call EntityLinker.resolve(ranked_context) → seed entity_ids.
    3. Skip gracefully if no seeds found.
    4. Build TraversalConfig from seeds + TraversalSettings.
    5. Call GraphTraversalClient.traverse(config).
    6. Append GraphContextItem list to ranked_context with source='knowledge_graph'.
    7. Update AgentState with graph_context_items, graph_tokens_used.
    """
    settings = TraversalSettings()

    ranked_context: list[dict] = state.get("ranked_context") or []
    execution_plan: dict = state.get("execution_plan") or {}

    remaining_budget: int = execution_plan.get("remaining_tokens", 0)
    token_budget = int(remaining_budget * settings.budget_fraction)

    with tracer.start_as_current_span("knowledge_graph.traverse") as span:
        span.set_attribute("kg.remaining_budget", remaining_budget)
        span.set_attribute("kg.token_budget", token_budget)

        if token_budget <= 0:
            logger.info("knowledge_graph_node: zero token budget — skipping traversal")
            span.set_attribute("kg.skipped", True)
            return {
                **state,
                "graph_traversal_skipped": True,
                "graph_tokens_used": 0,
                "graph_context_items": [],
            }

        # Resolve seeds
        client = GraphTraversalClient()
        linker = EntityLinker(traversal_client=client)
        seeds = await linker.resolve(ranked_context)

        if not seeds:
            logger.info("knowledge_graph_node: no seed entities found — skipping traversal")
            span.set_attribute("kg.skipped", True)
            return {
                **state,
                "graph_traversal_skipped": True,
                "graph_tokens_used": 0,
                "graph_context_items": [],
            }

        span.set_attribute("kg.seed_count", len(seeds))

        # Build traversal config
        config = TraversalConfig(
            seed_entity_ids=seeds,
            edge_types=list(EdgeType),
            max_depth=settings.max_depth,
            max_nodes_per_seed=settings.max_nodes_per_seed,
            token_budget=token_budget,
        )

        try:
            result = await client.traverse(config)
        except TimeoutError:
            logger.warning(
                "knowledge_graph_node: traversal timed out for seeds=%s", seeds
            )
            span.set_attribute("kg.timeout", True)
            return {
                **state,
                "graph_traversal_skipped": True,
                "graph_tokens_used": 0,
                "graph_context_items": [],
            }

        span.set_attribute("kg.items_returned", len(result.items))
        span.set_attribute("kg.tokens_used", result.total_tokens)
        span.set_attribute("kg.truncated", result.truncated)
        span.set_attribute("kg.duration_ms", result.query_duration_ms)

        langfuse.create_event(
            name="knowledge_graph_traversal",
            input={"seeds": seeds, "max_depth": config.max_depth},
            output={"items": len(result.items), "tokens": result.total_tokens},
            metadata={"duration_ms": result.query_duration_ms, "truncated": result.truncated},
        )

        # Append graph results to ranked_context (AC-4)
        graph_context_dicts = [item.model_dump() for item in result.items]
        updated_ranked_context = ranked_context + graph_context_dicts

        return {
            **state,
            "ranked_context": updated_ranked_context,
            "graph_context_items": result.items,
            "graph_traversal_skipped": False,
            "graph_tokens_used": result.total_tokens,
        }
