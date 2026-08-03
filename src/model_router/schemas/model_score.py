"""ModelScore output schema for the Dynamic Model Router (TASK-US019-02).

Holds the scored representation of a single candidate model after the
composite quality/cost/latency calculation.  Frozen so it can be safely
placed in sorted lists and cached across coroutines.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ModelScore(BaseModel):
    """Immutable scored representation of a candidate model."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    quality_score: float  # 0.0–1.0; derived from latency tier (proxy for capability quality)
    normalised_cost: float  # 1 / cost_per_1k_tokens; 1.0 for zero-cost models
    normalised_latency: float  # 1 / latency_tier_ordinal; see LATENCY_TIER_SCORE
    composite_score: float  # weighted sum — used for relative ranking only
