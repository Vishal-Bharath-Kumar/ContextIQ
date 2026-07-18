"""Unit tests for ModelDefinition schema, LatencyTier, and ModelCapability enums.

Acceptance criteria (TASK-US018-01):
- ModelRegistration with all required fields validates successfully
- capabilities=[] raises ValidationError (min_length=1)
- model_id with spaces raises ValidationError (URL-safe guard)
- model_id with slash passes validation
- cost_per_1k_tokens=0.0 is valid
- ModelDefinition.model_config = ConfigDict(from_attributes=True) — ORM coercion works
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.model_registry.schemas.model_definition import (
    LatencyTier,
    ModelCapability,
    ModelDefinition,
    ModelRegistration,
)

NOW = datetime(2026, 7, 18, 0, 0, 0, tzinfo=UTC)
MODEL_ID = uuid.uuid4()

VALID_PAYLOAD: dict = {
    "model_id": "gpt-4o-mini",
    "provider": "openai",
    "context_window": 128_000,
    "cost_per_1k_tokens": 0.15,
    "latency_tier": LatencyTier.FAST,
    "capabilities": [ModelCapability.CHAT, ModelCapability.FUNCTION_CALL],
    "is_active": True,
}


class TestModelRegistrationValid:
    def test_all_required_fields(self) -> None:
        reg = ModelRegistration(**VALID_PAYLOAD)
        assert reg.model_id == "gpt-4o-mini"
        assert reg.provider == "openai"
        assert reg.context_window == 128_000
        assert reg.cost_per_1k_tokens == 0.15
        assert reg.latency_tier is LatencyTier.FAST
        assert ModelCapability.CHAT in reg.capabilities
        assert reg.is_active is True

    def test_is_active_defaults_true(self) -> None:
        payload = {**VALID_PAYLOAD}
        payload.pop("is_active")
        reg = ModelRegistration(**payload)
        assert reg.is_active is True

    def test_slash_in_model_id(self) -> None:
        reg = ModelRegistration(**{**VALID_PAYLOAD, "model_id": "anthropic/claude-3-haiku"})
        assert reg.model_id == "anthropic/claude-3-haiku"

    def test_zero_cost_per_1k_tokens(self) -> None:
        reg = ModelRegistration(**{**VALID_PAYLOAD, "cost_per_1k_tokens": 0.0})
        assert reg.cost_per_1k_tokens == 0.0

    def test_all_latency_tiers(self) -> None:
        for tier in LatencyTier:
            reg = ModelRegistration(**{**VALID_PAYLOAD, "latency_tier": tier})
            assert reg.latency_tier is tier

    def test_all_capabilities_accepted(self) -> None:
        reg = ModelRegistration(**{**VALID_PAYLOAD, "capabilities": list(ModelCapability)})
        assert len(reg.capabilities) == len(ModelCapability)

    def test_single_capability(self) -> None:
        reg = ModelRegistration(**{**VALID_PAYLOAD, "capabilities": [ModelCapability.EMBEDDING]})
        assert reg.capabilities == [ModelCapability.EMBEDDING]

    def test_model_id_with_dots_and_dashes(self) -> None:
        reg = ModelRegistration(**{**VALID_PAYLOAD, "model_id": "gpt-4.5-turbo_v2"})
        assert reg.model_id == "gpt-4.5-turbo_v2"


class TestModelRegistrationInvalid:
    def test_empty_capabilities_raises(self) -> None:
        with pytest.raises(ValidationError, match="too_short"):
            ModelRegistration(**{**VALID_PAYLOAD, "capabilities": []})

    def test_model_id_with_space_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelRegistration(**{**VALID_PAYLOAD, "model_id": "gpt 4o mini"})

    def test_model_id_with_special_chars_raises(self) -> None:
        for bad_id in ("model@v1", "model#1", "model!id", "my model"):
            with pytest.raises(ValidationError):
                ModelRegistration(**{**VALID_PAYLOAD, "model_id": bad_id})

    def test_empty_model_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelRegistration(**{**VALID_PAYLOAD, "model_id": ""})

    def test_model_id_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelRegistration(**{**VALID_PAYLOAD, "model_id": "a" * 129})

    def test_provider_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelRegistration(**{**VALID_PAYLOAD, "provider": "p" * 65})

    def test_negative_context_window_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelRegistration(**{**VALID_PAYLOAD, "context_window": 0})

    def test_negative_cost_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelRegistration(**{**VALID_PAYLOAD, "cost_per_1k_tokens": -0.01})

    def test_invalid_latency_tier_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelRegistration(**{**VALID_PAYLOAD, "latency_tier": "ultrafast"})


class TestModelDefinitionOrmCoercion:
    def _make_orm_obj(self, **overrides: object) -> SimpleNamespace:
        base = {
            "id": MODEL_ID,
            "model_id": "gpt-4o-mini",
            "provider": "openai",
            "context_window": 128_000,
            "cost_per_1k_tokens": 0.15,
            "latency_tier": LatencyTier.FAST,
            "capabilities": [ModelCapability.CHAT],
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_from_attributes_coercion(self) -> None:
        orm_obj = self._make_orm_obj()
        defn = ModelDefinition.model_validate(orm_obj)
        assert defn.id == MODEL_ID
        assert defn.model_id == "gpt-4o-mini"
        assert defn.created_at == NOW
        assert defn.updated_at == NOW

    def test_from_attributes_config_set(self) -> None:
        assert ModelDefinition.model_config.get("from_attributes") is True

    def test_model_definition_includes_all_registration_fields(self) -> None:
        orm_obj = self._make_orm_obj()
        defn = ModelDefinition.model_validate(orm_obj)
        assert defn.provider == "openai"
        assert defn.context_window == 128_000
        assert defn.cost_per_1k_tokens == 0.15
        assert defn.latency_tier is LatencyTier.FAST
        assert defn.is_active is True


class TestEnums:
    def test_latency_tier_values(self) -> None:
        assert LatencyTier.FAST == "fast"
        assert LatencyTier.MEDIUM == "medium"
        assert LatencyTier.SLOW == "slow"

    def test_model_capability_values(self) -> None:
        assert ModelCapability.CHAT == "chat"
        assert ModelCapability.COMPLETION == "completion"
        assert ModelCapability.EMBEDDING == "embedding"
        assert ModelCapability.CODE == "code"
        assert ModelCapability.SUMMARIZATION == "summarization"
        assert ModelCapability.VISION == "vision"
        assert ModelCapability.FUNCTION_CALL == "function_call"

    def test_latency_tier_is_str(self) -> None:
        assert isinstance(LatencyTier.FAST, str)

    def test_model_capability_is_str(self) -> None:
        assert isinstance(ModelCapability.CHAT, str)
