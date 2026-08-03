"""Conditional edge predicates for the ContextIQ multi-agent pipeline.

These functions are used as routing keys in ``StateGraph.add_conditional_edges``
calls inside ``build_graph()``.  They are pure functions of ``AgentState`` and
must never produce side-effects.
"""

from __future__ import annotations

from src.agents.config import INTENT_CONFIDENCE_THRESHOLD, MAX_CLARIFICATION_ROUNDS
from src.agents.state import AgentState, ExecutionStatus
from src.retrieval.ranking.filters import count_tokens


def route_after_intent(state: AgentState) -> str:
    """Return the next node key after the intent_agent executes.

    Routing rules (evaluated in order):
    1. If the pipeline has already failed, short-circuit to ``"failed"``.
    2. If ``intent_confidence`` is below threshold and ``clarification_round``
       is 0, request clarification (US-011 AC-6).
    3. If ``intent_confidence`` is below threshold and the cap has been reached
       (``clarification_round >= MAX_CLARIFICATION_ROUNDS``), force retrieval
       with fallback sources rather than issuing a second question.
    4. Otherwise proceed to retrieval.

    Returns:
        One of ``"retrieval"``, ``"clarification"``, or ``"failed"``.
    """
    if state.get("status") == ExecutionStatus.FAILED:
        return "failed"

    confidence = state["intent_confidence"]
    clarification_round = state.get("clarification_round", 0)

    if (confidence if confidence is not None else 1.0) < INTENT_CONFIDENCE_THRESHOLD:
        if clarification_round >= MAX_CLARIFICATION_ROUNDS:
            return "retrieval"
        return "clarification"

    return "retrieval"


def route_after_governance(state: AgentState) -> str:
    """Return the next node key after the governance_agent executes.

    Routing rules (evaluated in order):
    1. If the pipeline has already failed, short-circuit to ``"failed"``.
    2. Compare cumulative token count of ranked context against the token
       budget declared in the execution plan.  If the context exceeds the
       budget, route to compression; otherwise skip directly to routing.

    The default token budget when ``execution_plan`` is absent or has no
    ``token_budget_total`` key is **8 000 tokens**.

    Returns:
        One of ``"compress"``, ``"skip"``, or ``"failed"``.
    """
    if state.get("status") == ExecutionStatus.FAILED:
        return "failed"
    execution_plan = state.get("execution_plan")
    if isinstance(execution_plan, dict):
        budget = int(execution_plan.get("token_budget_total") or 8_000)
    elif execution_plan is not None:
        budget = int(execution_plan.token_budget_total)
    else:
        budget = 8_000
    ranked_tokens: int = sum(
        _chunk_token_count(c) for c in (state.get("ranked_context") or [])
    )
    return "compress" if ranked_tokens > budget else "skip"


def _chunk_token_count(chunk: object) -> int:
    if isinstance(chunk, dict):
        raw_token_count = chunk.get("token_count")
        if raw_token_count is not None:
            return int(raw_token_count)
        text = str(chunk.get("content") or chunk.get("text") or chunk.get("path_summary") or "")
        return count_tokens(text)

    raw_token_count = getattr(chunk, "token_count", None)
    if raw_token_count is not None:
        return int(raw_token_count)

    text = str(getattr(chunk, "content", "") or getattr(chunk, "path_summary", "") or "")
    return count_tokens(text)
