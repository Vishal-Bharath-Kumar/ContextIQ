"""Token budget allocator for the ContextIQ agent pipeline (AIR-009 / EP-003)."""

from __future__ import annotations

from src.agents.schemas.intent import IntentType

# Relative weight per source for a given intent type.
# Sources not listed in a row receive weight 1 (equal share).
SOURCE_WEIGHT_TABLE: dict[IntentType, dict[str, int]] = {
    IntentType.DEBUGGING:    {"github": 3, "stackoverflow": 3, "jira": 2},
    IntentType.CODE_GEN:     {"github": 4, "confluence": 2},
    IntentType.ARCHITECTURE: {"confluence": 4, "github": 2, "miro": 2},
    IntentType.DOCS:         {"confluence": 4, "github": 2},
    IntentType.INCIDENT:     {"grafana": 4, "jira": 3, "pagerduty": 2},
    IntentType.METRICS:      {"grafana": 4, "datadog": 3},
    IntentType.CODE_REVIEW:  {"github": 1},
    IntentType.GENERAL:      {"confluence": 2, "github": 2, "stackoverflow": 2},
}

DEFAULT_TOTAL_BUDGET: int = 8_000


def allocate_token_budget(
    intent_type: IntentType,
    source_list: list[str],
    total_budget: int = DEFAULT_TOTAL_BUDGET,
) -> dict[str, int]:
    """Distribute ``total_budget`` tokens across ``source_list`` using intent weights.

    Returns a mapping of source_id → token quota.
    Minimum allocation per source is 200 tokens to prevent starvation.
    """
    if not source_list:
        return {}

    weight_row = SOURCE_WEIGHT_TABLE.get(intent_type, {})
    weights = {src: weight_row.get(src, 1) for src in source_list}
    total_weight = sum(weights.values())

    MIN_ALLOC = 200
    allocations: dict[str, int] = {}
    remainder = total_budget

    # Proportional allocation with floor guarantee
    for src in source_list[:-1]:  # all but last
        raw = int(total_budget * weights[src] / total_weight)
        quota = max(raw, MIN_ALLOC)
        allocations[src] = quota
        remainder -= quota

    # Last source absorbs rounding remainder
    allocations[source_list[-1]] = max(remainder, MIN_ALLOC)

    return allocations
