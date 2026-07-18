"""RankingWeights model and per-intent weight table (AIR-011 canonical defaults).

Weights drive the combined scoring formula used by the governance node (US-014-05):
    combined_score = vector_weight * vector_score
                   + keyword_weight * keyword_score
                   + recency_weight * recency_score
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agents.schemas.intent import IntentType


class RankingWeights(BaseModel):
    """Per-intent weights for the combined scoring formula.

    All three weights must sum to 1.0 (tolerance ±0.001).
    """

    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    recency_weight: float = Field(default=0.2, ge=0.0, le=1.0)

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> RankingWeights:
        total = self.vector_weight + self.keyword_weight + self.recency_weight
        if not (0.999 < total < 1.001):
            raise ValueError(f"Weights must sum to 1.0, got {total:.4f}")
        return self


# Per-intent canonical defaults (AIR-011)
INTENT_WEIGHT_TABLE: dict[IntentType, RankingWeights] = {
    IntentType.DEBUGGING: RankingWeights(
        vector_weight=0.5, keyword_weight=0.3, recency_weight=0.2
    ),
    IntentType.CODE_GEN: RankingWeights(
        vector_weight=0.7, keyword_weight=0.1, recency_weight=0.2
    ),
    IntentType.ARCHITECTURE: RankingWeights(
        vector_weight=0.7, keyword_weight=0.1, recency_weight=0.2
    ),
    IntentType.DOCS: RankingWeights(
        vector_weight=0.6, keyword_weight=0.2, recency_weight=0.2
    ),
    IntentType.INCIDENT: RankingWeights(
        vector_weight=0.3, keyword_weight=0.5, recency_weight=0.2
    ),
    IntentType.METRICS: RankingWeights(
        vector_weight=0.2, keyword_weight=0.6, recency_weight=0.2
    ),
    IntentType.CODE_REVIEW: RankingWeights(
        vector_weight=0.6, keyword_weight=0.2, recency_weight=0.2
    ),
    IntentType.GENERAL: RankingWeights(
        vector_weight=0.6, keyword_weight=0.2, recency_weight=0.2
    ),
}

DEFAULT_WEIGHTS = RankingWeights()  # 0.6 / 0.2 / 0.2
