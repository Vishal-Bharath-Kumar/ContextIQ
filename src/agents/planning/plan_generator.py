"""Execution plan generator for the ContextIQ agent pipeline (AIR-007 / EP-003).

``generate_execution_plan()`` is a pure function — no I/O, no LLM calls.
It performs only dict lookups and integer arithmetic, so p99 latency < 1 ms.
Called synchronously at the end of ``intent_node()`` after source selection.
"""

from __future__ import annotations

from src.agents.planning.token_budget import DEFAULT_TOTAL_BUDGET, allocate_token_budget
from src.agents.schemas.execution_plan import ExecutionPlan, RankingStrategy
from src.agents.schemas.intent import IntentType

RANKING_STRATEGY_MAP: dict[IntentType, RankingStrategy] = {
    IntentType.DEBUGGING: RankingStrategy.HYBRID,
    IntentType.CODE_GEN: RankingStrategy.SEMANTIC,
    IntentType.ARCHITECTURE: RankingStrategy.SEMANTIC,
    IntentType.DOCS: RankingStrategy.SEMANTIC,
    IntentType.INCIDENT: RankingStrategy.BM25,
    IntentType.METRICS: RankingStrategy.BM25,
    IntentType.CODE_REVIEW: RankingStrategy.HYBRID,
    IntentType.GENERAL: RankingStrategy.HYBRID,
}

# Cache-eligible intent types: results are stable and unlikely to change
# between requests with identical prompts within a TTL window
CACHE_ELIGIBLE_INTENTS: frozenset[IntentType] = frozenset({
    IntentType.DOCS,
    IntentType.ARCHITECTURE,
    IntentType.CODE_GEN,
})


def generate_execution_plan(
    intent_type: IntentType,
    confidence: float,
    source_list: list[str],
    total_budget: int = DEFAULT_TOTAL_BUDGET,
) -> ExecutionPlan:
    """Assemble a fully-specified ExecutionPlan from the intent classification result.

    Called synchronously at the end of intent_node() — no I/O, must complete < 200 ms.
    """
    return ExecutionPlan(
        sources=source_list,
        token_budget_total=total_budget,
        token_budget_per_source=allocate_token_budget(intent_type, source_list, total_budget),
        ranking_strategy=RANKING_STRATEGY_MAP[intent_type],
        cache_eligible=intent_type in CACHE_ELIGIBLE_INTENTS,
    )
