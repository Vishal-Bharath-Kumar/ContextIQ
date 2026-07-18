"""Model scoring logic for the Dynamic Model Router (TASK-US019-02).

Provides:
- ``LATENCY_TIER_ORDINAL``  — ordinal mapping used for normalised_latency
- ``LATENCY_TIER_QUALITY``  — quality proxy derived from latency tier
- ``compute_model_score()`` — pure function; no I/O, no side effects
"""

from __future__ import annotations

from src.model_registry.schemas.model_definition import LatencyTier, ModelDefinition
from src.model_router.schemas.model_score import ModelScore
from src.model_router.schemas.routing_weights import RoutingWeights

# ---------------------------------------------------------------------------
# Tier mappings
# ---------------------------------------------------------------------------

# Ordinal: FAST=1, MEDIUM=2, SLOW=3 (higher ordinal → lower latency score)
LATENCY_TIER_ORDINAL: dict[LatencyTier, int] = {
    LatencyTier.FAST: 1,
    LatencyTier.MEDIUM: 2,
    LatencyTier.SLOW: 3,
}

# Quality proxy: SLOW models score highest on the quality dimension
# because heavier reasoning correlates with higher capability.
LATENCY_TIER_QUALITY: dict[LatencyTier, float] = {
    LatencyTier.FAST: 0.60,
    LatencyTier.MEDIUM: 0.80,
    LatencyTier.SLOW: 1.00,
}

_COST_EPSILON: float = 1e-6  # prevent division by zero for zero-cost models

# ---------------------------------------------------------------------------
# Scoring function
# ---------------------------------------------------------------------------


def compute_model_score(model: ModelDefinition, weights: RoutingWeights) -> ModelScore:
    """Return a :class:`ModelScore` for *model* using the supplied *weights*.

    The composite score is used only for **relative ranking** within a
    candidate list; callers must not interpret the raw value as a probability.
    """
    quality_score = LATENCY_TIER_QUALITY[model.latency_tier]
    normalised_cost = 1.0 / (model.cost_per_1k_tokens + _COST_EPSILON)
    normalised_latency = 1.0 / LATENCY_TIER_ORDINAL[model.latency_tier]

    composite = (
        weights.quality_weight * quality_score
        + weights.cost_weight * normalised_cost
        + weights.latency_weight * normalised_latency
    )

    return ModelScore(
        model_id=model.model_id,
        quality_score=quality_score,
        normalised_cost=normalised_cost,
        normalised_latency=normalised_latency,
        composite_score=composite,
    )
