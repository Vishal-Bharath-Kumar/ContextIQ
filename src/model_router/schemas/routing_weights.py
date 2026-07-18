"""RoutingWeights schema and per-intent preset table (TASK-US019-01).

``RoutingWeights`` is a frozen Pydantic model that encodes the relative
importance of quality, cost, and latency for a given routing decision.
``INTENT_ROUTING_WEIGHT_TABLE`` maps every ``IntentType`` to a preset so
the routing node can immediately resolve weights without a database lookup.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from src.agents.schemas.intent import IntentType


class RoutingWeights(BaseModel):
    """Immutable weight vector for model routing (quality / cost / latency).

    All three weights must sum to exactly 1.0.
    """

    model_config = ConfigDict(frozen=True)

    quality_weight: float  # 0.0 – 1.0
    cost_weight: float  # 0.0 – 1.0
    latency_weight: float  # 0.0 – 1.0

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> RoutingWeights:
        total = round(self.quality_weight + self.cost_weight + self.latency_weight, 6)
        if total != 1.0:
            raise ValueError(f"Routing weights must sum to 1.0, got {total}")
        return self


# ---------------------------------------------------------------------------
# Per-intent routing weight presets
# Mirrors the 8 IntentType entries in SOURCE_MAP (TASK-US009-03).
# ---------------------------------------------------------------------------
INTENT_ROUTING_WEIGHT_TABLE: dict[str, RoutingWeights] = {
    # Correctness critical; cost secondary
    IntentType.CODE_GEN: RoutingWeights(quality_weight=0.70, cost_weight=0.20, latency_weight=0.10),
    # Nuanced analysis; cost moderate
    IntentType.CODE_REVIEW: RoutingWeights(quality_weight=0.65, cost_weight=0.25, latency_weight=0.10),
    # Balanced design quality with moderate cost sensitivity
    IntentType.ARCHITECTURE: RoutingWeights(quality_weight=0.60, cost_weight=0.30, latency_weight=0.10),
    # Balanced; documentation tolerates slightly higher cost
    IntentType.DOCS: RoutingWeights(quality_weight=0.40, cost_weight=0.40, latency_weight=0.20),
    # Incident response: latency elevated; still needs quality
    IntentType.INCIDENT: RoutingWeights(quality_weight=0.50, cost_weight=0.20, latency_weight=0.30),
    # Cost-first for metrics summarisation; quality good enough
    IntentType.METRICS: RoutingWeights(quality_weight=0.30, cost_weight=0.50, latency_weight=0.20),
    # Reasoning-heavy debugging; cost secondary
    IntentType.DEBUGGING: RoutingWeights(quality_weight=0.65, cost_weight=0.25, latency_weight=0.10),
    # Balanced fallback for general intents
    IntentType.GENERAL: RoutingWeights(quality_weight=0.40, cost_weight=0.40, latency_weight=0.20),
}
