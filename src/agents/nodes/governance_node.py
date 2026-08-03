"""Context-ranking node for the ContextIQ pipeline (TASK-US014-05).

Position: between knowledge_graph node and governance_agent (PII scan) node.

Instantiates ``ContextRanker`` with the intent-appropriate ``RankingWeights``,
calls ``rank()`` on ``AgentState.raw_context``, and writes the result to
``AgentState.ranked_context``.  Replaces the ``ranked_context = raw_context``
pass-through stub from TASK-US007-01.

The ``route_after_governance`` predicate (TASK-US006-01) reads ``ranked_context``
after the OPA filter to decide compress-vs-skip.
"""

from __future__ import annotations

from src.agents.schemas.intent import IntentType
from src.agents.state import AgentState, ExecutionStatus
from src.retrieval.ranking.ranker import ContextRanker
from src.retrieval.ranking.settings import RankingSettings
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk

# Module-level singleton — initialised once at import; never re-created per request.
_ranking_settings = RankingSettings()


async def governance_node(state: AgentState) -> dict:
    """LangGraph node — context ranking gate.

    Reads ``raw_context`` from *state*, scores every chunk with the
    intent-appropriate ``RankingWeights``, filters below the relevance
    threshold, sorts descending, and truncates to the token budget declared
    in ``execution_plan.token_budget_total``.

    Returns an empty list (not ``None``) when ``raw_context`` is absent or
    empty, so downstream nodes never need to guard against ``None``.

    Args:
        state: Current ``AgentState`` produced by the upstream retrieval and
               knowledge-graph nodes.

    Returns:
        Partial state update containing ``ranked_context``, ``current_node``,
        and ``status``.
    """
    raw_context: list[RetrievedChunk] = state.get("raw_context") or []
    intent_type = IntentType(state["intent_type"])
    token_budget: int = state["execution_plan"].token_budget_total

    weights = _ranking_settings.get_weights(intent_type)
    ranker = ContextRanker(
        weights=weights,
        threshold=_ranking_settings.relevance_threshold,
    )

    ranked = ranker.rank(raw_context, token_budget)

    return {
        "ranked_context": ranked,
        "current_node": "governance_agent",
        "status": ExecutionStatus.RUNNING,
    }
