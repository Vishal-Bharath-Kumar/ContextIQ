"""Unit tests for compute_model_score() and LATENCY_TIER_QUALITY (TASK-US019-02)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from src.model_registry.schemas.model_definition import (
    LatencyTier,
    ModelCapability,
    ModelDefinition,
)
from src.model_router.schemas.model_score import ModelScore
from src.model_router.schemas.routing_weights import RoutingWeights
from src.model_router.scoring import (
    LATENCY_TIER_ORDINAL,
    LATENCY_TIER_QUALITY,
    compute_model_score,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make_model(
    model_id: str = "test-model",
    cost_per_1k_tokens: float = 0.002,
    latency_tier: LatencyTier = LatencyTier.MEDIUM,
) -> ModelDefinition:
    return ModelDefinition(
        id=uuid.uuid4(),
        model_id=model_id,
        provider="test-provider",
        context_window=8192,
        cost_per_1k_tokens=cost_per_1k_tokens,
        latency_tier=latency_tier,
        capabilities=[ModelCapability.CHAT],
        created_at=_NOW,
        updated_at=_NOW,
    )


_EQUAL_WEIGHTS = RoutingWeights(
    quality_weight=round(1 / 3, 6),
    cost_weight=round(1 / 3, 6),
    latency_weight=round(1 - 2 * round(1 / 3, 6), 6),
)

_QUALITY_FOCUSED = RoutingWeights(quality_weight=0.7, cost_weight=0.2, latency_weight=0.1)
_COST_FOCUSED = RoutingWeights(quality_weight=0.1, cost_weight=0.8, latency_weight=0.1)
_LATENCY_FOCUSED = RoutingWeights(quality_weight=0.1, cost_weight=0.1, latency_weight=0.8)


# ---------------------------------------------------------------------------
# LATENCY_TIER_QUALITY assertions
# ---------------------------------------------------------------------------


class TestLatencyTierQuality:
    def test_slow_scores_highest(self) -> None:
        assert LATENCY_TIER_QUALITY[LatencyTier.SLOW] == 1.0

    def test_medium_scores_above_fast(self) -> None:
        assert LATENCY_TIER_QUALITY[LatencyTier.MEDIUM] > LATENCY_TIER_QUALITY[LatencyTier.FAST]

    def test_all_tiers_in_valid_range(self) -> None:
        for tier, score in LATENCY_TIER_QUALITY.items():
            assert 0.0 <= score <= 1.0, f"{tier}: quality score {score} out of [0, 1]"

    def test_all_tiers_covered(self) -> None:
        assert set(LATENCY_TIER_QUALITY.keys()) == set(LatencyTier)


# ---------------------------------------------------------------------------
# compute_model_score — composite value
# ---------------------------------------------------------------------------


class TestComputeModelScore:
    def test_returns_model_score_instance(self) -> None:
        model = _make_model(latency_tier=LatencyTier.FAST)
        result = compute_model_score(model, _EQUAL_WEIGHTS)
        assert isinstance(result, ModelScore)

    def test_model_id_preserved(self) -> None:
        model = _make_model(model_id="my-model", latency_tier=LatencyTier.FAST)
        result = compute_model_score(model, _EQUAL_WEIGHTS)
        assert result.model_id == "my-model"

    def test_composite_equals_manual_weighted_sum(self) -> None:
        model = _make_model(cost_per_1k_tokens=0.01, latency_tier=LatencyTier.MEDIUM)
        weights = _QUALITY_FOCUSED

        quality = LATENCY_TIER_QUALITY[LatencyTier.MEDIUM]
        normalised_cost = 1.0 / (0.01 + 1e-6)
        normalised_latency = 1.0 / LATENCY_TIER_ORDINAL[LatencyTier.MEDIUM]

        expected = (
            weights.quality_weight * quality
            + weights.cost_weight * normalised_cost
            + weights.latency_weight * normalised_latency
        )

        result = compute_model_score(model, weights)
        assert result.composite_score == pytest.approx(expected, rel=1e-9)

    @pytest.mark.parametrize("tier", list(LatencyTier))
    def test_quality_score_matches_tier_quality_map(self, tier: LatencyTier) -> None:
        model = _make_model(latency_tier=tier)
        result = compute_model_score(model, _EQUAL_WEIGHTS)
        assert result.quality_score == LATENCY_TIER_QUALITY[tier]

    @pytest.mark.parametrize("tier", list(LatencyTier))
    def test_normalised_latency_matches_ordinal_inverse(self, tier: LatencyTier) -> None:
        model = _make_model(latency_tier=tier)
        result = compute_model_score(model, _EQUAL_WEIGHTS)
        assert result.normalised_latency == pytest.approx(1.0 / LATENCY_TIER_ORDINAL[tier])

    # ------------------------------------------------------------------
    # Zero-cost guard
    # ------------------------------------------------------------------

    def test_zero_cost_does_not_raise_division_error(self) -> None:
        model = _make_model(cost_per_1k_tokens=0.0, latency_tier=LatencyTier.FAST)
        result = compute_model_score(model, _COST_FOCUSED)
        # normalised_cost ≈ 1/epsilon — just ensure it is a finite positive number
        assert result.normalised_cost > 0
        assert result.composite_score > 0

    def test_zero_cost_normalised_cost_uses_epsilon(self) -> None:
        model = _make_model(cost_per_1k_tokens=0.0)
        result = compute_model_score(model, _EQUAL_WEIGHTS)
        expected_cost = 1.0 / (0.0 + 1e-6)
        assert result.normalised_cost == pytest.approx(expected_cost)

    # ------------------------------------------------------------------
    # Relative ranking
    # ------------------------------------------------------------------

    def test_slow_model_outranks_fast_on_quality_weight(self) -> None:
        """SLOW model should score higher when quality weight dominates."""
        slow = _make_model(model_id="slow", cost_per_1k_tokens=0.01, latency_tier=LatencyTier.SLOW)
        fast = _make_model(model_id="fast", cost_per_1k_tokens=0.01, latency_tier=LatencyTier.FAST)
        slow_score = compute_model_score(slow, _QUALITY_FOCUSED)
        fast_score = compute_model_score(fast, _QUALITY_FOCUSED)
        assert slow_score.composite_score > fast_score.composite_score

    def test_fast_model_outranks_slow_on_latency_weight(self) -> None:
        """FAST model should score higher when latency weight dominates."""
        slow = _make_model(model_id="slow", cost_per_1k_tokens=0.01, latency_tier=LatencyTier.SLOW)
        fast = _make_model(model_id="fast", cost_per_1k_tokens=0.01, latency_tier=LatencyTier.FAST)
        slow_score = compute_model_score(slow, _LATENCY_FOCUSED)
        fast_score = compute_model_score(fast, _LATENCY_FOCUSED)
        assert fast_score.composite_score > slow_score.composite_score

    # ------------------------------------------------------------------
    # Immutability
    # ------------------------------------------------------------------

    def test_returned_score_is_frozen(self) -> None:
        model = _make_model(latency_tier=LatencyTier.FAST)
        result = compute_model_score(model, _EQUAL_WEIGHTS)
        with pytest.raises((TypeError, Exception)):
            result.composite_score = 0.0  # type: ignore[misc]
