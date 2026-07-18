"""Unit tests for RankingWeights and INTENT_WEIGHT_TABLE (TASK-US014-01)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agents.schemas.intent import IntentType
from src.retrieval.ranking.weights import (
    DEFAULT_WEIGHTS,
    INTENT_WEIGHT_TABLE,
    RankingWeights,
)

# ---------------------------------------------------------------------------
# RankingWeights — default construction
# ---------------------------------------------------------------------------


class TestRankingWeightsDefaults:
    def test_default_vector_weight(self) -> None:
        assert RankingWeights().vector_weight == 0.6

    def test_default_keyword_weight(self) -> None:
        assert RankingWeights().keyword_weight == 0.2

    def test_default_recency_weight(self) -> None:
        assert RankingWeights().recency_weight == 0.2

    def test_default_weights_sum_to_one(self) -> None:
        w = RankingWeights()
        assert abs(w.vector_weight + w.keyword_weight + w.recency_weight - 1.0) < 1e-9

    def test_default_weights_constant_matches_defaults(self) -> None:
        assert DEFAULT_WEIGHTS == RankingWeights()

    def test_model_is_frozen(self) -> None:
        w = RankingWeights()
        with pytest.raises((TypeError, ValidationError)):
            w.vector_weight = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RankingWeights — validator: weights must sum to 1.0
# ---------------------------------------------------------------------------


class TestRankingWeightsValidator:
    def test_valid_custom_weights(self) -> None:
        w = RankingWeights(vector_weight=0.5, keyword_weight=0.3, recency_weight=0.2)
        assert abs(w.vector_weight + w.keyword_weight + w.recency_weight - 1.0) < 1e-9

    def test_invalid_weights_sum_gt_one_raises(self) -> None:
        """AC: sum > 1.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            RankingWeights(vector_weight=0.5, keyword_weight=0.6, recency_weight=0.2)

    def test_invalid_weights_sum_lt_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            RankingWeights(vector_weight=0.3, keyword_weight=0.1, recency_weight=0.1)

    def test_weight_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            RankingWeights(vector_weight=-0.1, keyword_weight=0.6, recency_weight=0.5)

    def test_weight_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            RankingWeights(vector_weight=1.1, keyword_weight=0.0, recency_weight=0.0)


# ---------------------------------------------------------------------------
# INTENT_WEIGHT_TABLE — coverage and correctness
# ---------------------------------------------------------------------------


class TestIntentWeightTable:
    _ALL_INTENTS = list(IntentType)

    def test_all_intent_types_present(self) -> None:
        """AC: all 8 IntentType values are keys in INTENT_WEIGHT_TABLE."""
        assert set(INTENT_WEIGHT_TABLE.keys()) == set(IntentType)

    def test_table_has_eight_entries(self) -> None:
        assert len(INTENT_WEIGHT_TABLE) == 8

    @pytest.mark.parametrize("intent", list(IntentType))
    def test_each_entry_passes_validator(self, intent: IntentType) -> None:
        """AC: every entry in INTENT_WEIGHT_TABLE passes weights_sum_to_one."""
        w = INTENT_WEIGHT_TABLE[intent]
        total = w.vector_weight + w.keyword_weight + w.recency_weight
        assert abs(total - 1.0) < 1e-9, f"{intent}: weights sum to {total}"

    def test_debugging_keyword_weight_higher_than_code_gen(self) -> None:
        """DEBUGGING prioritises keyword retrieval; CODE_GEN prioritises vector."""
        assert (
            INTENT_WEIGHT_TABLE[IntentType.DEBUGGING].keyword_weight
            > INTENT_WEIGHT_TABLE[IntentType.CODE_GEN].keyword_weight
        )

    def test_metrics_keyword_weight_highest(self) -> None:
        """METRICS has highest keyword_weight (0.6) among all intents."""
        metrics_kw = INTENT_WEIGHT_TABLE[IntentType.METRICS].keyword_weight
        for intent, w in INTENT_WEIGHT_TABLE.items():
            if intent != IntentType.METRICS:
                assert metrics_kw >= w.keyword_weight

    def test_metrics_keyword_weight(self) -> None:
        assert INTENT_WEIGHT_TABLE[IntentType.METRICS].keyword_weight == 0.6

    def test_code_gen_vector_weight(self) -> None:
        assert INTENT_WEIGHT_TABLE[IntentType.CODE_GEN].vector_weight == 0.7

    def test_architecture_vector_weight(self) -> None:
        assert INTENT_WEIGHT_TABLE[IntentType.ARCHITECTURE].vector_weight == 0.7
