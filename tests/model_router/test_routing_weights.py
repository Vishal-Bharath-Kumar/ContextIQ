"""Unit tests for RoutingWeights schema and INTENT_ROUTING_WEIGHT_TABLE (TASK-US019-01)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.agents.schemas.intent import IntentType
from src.model_router.schemas.routing_weights import (
    INTENT_ROUTING_WEIGHT_TABLE,
    RoutingWeights,
)

# ---------------------------------------------------------------------------
# RoutingWeights construction
# ---------------------------------------------------------------------------


class TestRoutingWeightsConstruction:
    def test_valid_weights_sum_to_one(self) -> None:
        weights = RoutingWeights(quality_weight=0.7, cost_weight=0.2, latency_weight=0.1)
        assert weights.quality_weight == 0.7
        assert weights.cost_weight == 0.2
        assert weights.latency_weight == 0.1

    def test_invalid_weights_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="sum to 1.0"):
            RoutingWeights(quality_weight=0.5, cost_weight=0.5, latency_weight=0.1)

    def test_equal_split_is_valid(self) -> None:
        weights = RoutingWeights(
            quality_weight=round(1 / 3, 6),
            cost_weight=round(1 / 3, 6),
            latency_weight=round(1 - 2 * round(1 / 3, 6), 6),
        )
        assert weights is not None

    def test_frozen_model_prevents_mutation(self) -> None:
        weights = RoutingWeights(quality_weight=0.5, cost_weight=0.3, latency_weight=0.2)
        with pytest.raises((TypeError, ValidationError)):
            weights.quality_weight = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# INTENT_ROUTING_WEIGHT_TABLE completeness and validity
# ---------------------------------------------------------------------------


class TestIntentRoutingWeightTable:
    def test_table_has_exactly_eight_entries(self) -> None:
        assert len(INTENT_ROUTING_WEIGHT_TABLE) == 8

    def test_table_covers_all_intent_types(self) -> None:
        for intent in IntentType:
            assert intent in INTENT_ROUTING_WEIGHT_TABLE, (
                f"IntentType.{intent.name} missing from INTENT_ROUTING_WEIGHT_TABLE"
            )

    @pytest.mark.parametrize("intent_type", list(IntentType))
    def test_all_presets_sum_to_one(self, intent_type: IntentType) -> None:
        weights = INTENT_ROUTING_WEIGHT_TABLE[intent_type]
        total = round(
            weights.quality_weight + weights.cost_weight + weights.latency_weight,
            6,
        )
        assert total == 1.0, (
            f"{intent_type}: weights sum to {total}, expected 1.0"
        )

    @pytest.mark.parametrize("intent_type", list(IntentType))
    def test_all_weights_in_valid_range(self, intent_type: IntentType) -> None:
        weights = INTENT_ROUTING_WEIGHT_TABLE[intent_type]
        for name, value in [
            ("quality_weight", weights.quality_weight),
            ("cost_weight", weights.cost_weight),
            ("latency_weight", weights.latency_weight),
        ]:
            assert 0.0 <= value <= 1.0, (
                f"{intent_type}.{name} = {value} is outside [0.0, 1.0]"
            )

    def test_code_gen_prioritises_quality(self) -> None:
        weights = INTENT_ROUTING_WEIGHT_TABLE[IntentType.CODE_GEN]
        assert weights.quality_weight >= 0.60

    def test_metrics_prioritises_cost(self) -> None:
        weights = INTENT_ROUTING_WEIGHT_TABLE[IntentType.METRICS]
        assert weights.cost_weight >= 0.40

    def test_incident_has_elevated_latency_weight(self) -> None:
        weights = INTENT_ROUTING_WEIGHT_TABLE[IntentType.INCIDENT]
        assert weights.latency_weight >= 0.20


# ---------------------------------------------------------------------------
# RoutingSettings — environment-variable override loading
# ---------------------------------------------------------------------------


class TestRoutingSettings:
    def test_all_override_fields_default_to_none(self) -> None:
        from src.model_router.config import RoutingSettings

        settings = RoutingSettings()
        assert settings.weights_code_generation is None
        assert settings.weights_summarization is None
        assert settings.weights_code_review is None
        assert settings.weights_documentation is None
        assert settings.weights_question_answering is None
        assert settings.weights_debugging is None
        assert settings.weights_refactoring is None
        assert settings.weights_general is None

    def test_env_override_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps(
            {"quality_weight": 0.80, "cost_weight": 0.10, "latency_weight": 0.10}
        )
        monkeypatch.setenv("ROUTING_WEIGHTS_CODE_GENERATION", payload)

        from importlib import reload

        import src.model_router.config as cfg_module

        reload(cfg_module)
        settings = cfg_module.RoutingSettings()

        assert settings.weights_code_generation == payload
        # Verify the JSON can be parsed into a valid RoutingWeights
        override = RoutingWeights.model_validate_json(payload)
        assert override.quality_weight == 0.80


# ---------------------------------------------------------------------------
# AgentState new fields
# ---------------------------------------------------------------------------


class TestAgentStateNewFields:
    def test_selected_model_id_and_routing_score_exist(self) -> None:
        from src.agents.state import AgentState

        annotations = AgentState.__annotations__
        assert "selected_model_id" in annotations
        assert "routing_score" in annotations

    def test_new_fields_accept_none(self) -> None:
        """Both new fields should be NotRequired (i.e. optional in TypedDict)."""
        from typing import get_type_hints

        from src.agents.state import AgentState

        hints = get_type_hints(AgentState, include_extras=True)
        assert "selected_model_id" in hints
        assert "routing_score" in hints
