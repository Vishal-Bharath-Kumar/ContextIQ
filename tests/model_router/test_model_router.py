"""Unit tests for ModelRouter and INTENT_CAPABILITY_MAP (TASK-US019-03)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.agents.schemas.intent import IntentType
from src.model_registry.schemas.model_definition import (
    LatencyTier,
    ModelCapability,
    ModelDefinition,
)
from src.model_router.router import INTENT_CAPABILITY_MAP, ModelRouter
from src.model_router.schemas.model_score import ModelScore
from src.model_router.schemas.routing_weights import RoutingWeights

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make_model(
    model_id: str = "test-model",
    capabilities: list[ModelCapability] | None = None,
    latency_tier: LatencyTier = LatencyTier.FAST,
    cost_per_1k_tokens: float = 0.002,
) -> ModelDefinition:
    return ModelDefinition(
        id=uuid.uuid4(),
        model_id=model_id,
        provider="test-provider",
        context_window=8192,
        cost_per_1k_tokens=cost_per_1k_tokens,
        latency_tier=latency_tier,
        capabilities=capabilities or [ModelCapability.CHAT],
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_score(model_id: str, composite: float = 0.75) -> ModelScore:
    return ModelScore(
        model_id=model_id,
        quality_score=0.6,
        normalised_cost=500.0,
        normalised_latency=1.0,
        composite_score=composite,
    )


def _make_router(
    list_cache_return: list[ModelDefinition] | None = None,
    scored_cache_return: list[ModelScore] | None = None,
) -> tuple[ModelRouter, AsyncMock, AsyncMock]:
    model_list_cache = AsyncMock()
    model_list_cache.get = AsyncMock(return_value=list_cache_return)

    scored_model_cache = AsyncMock()
    scored_model_cache.get = AsyncMock(return_value=scored_cache_return)
    scored_model_cache.set = AsyncMock()

    router = ModelRouter(
        model_list_cache=model_list_cache,
        scored_model_cache=scored_model_cache,
    )
    return router, model_list_cache, scored_model_cache


# ---------------------------------------------------------------------------
# INTENT_CAPABILITY_MAP completeness
# ---------------------------------------------------------------------------


class TestIntentCapabilityMap:
    def test_covers_all_intent_types(self) -> None:
        for intent in IntentType:
            assert intent in INTENT_CAPABILITY_MAP, (
                f"IntentType.{intent.name} missing from INTENT_CAPABILITY_MAP"
            )

    def test_has_exactly_eight_entries(self) -> None:
        assert len(INTENT_CAPABILITY_MAP) == 8

    def test_code_gen_maps_to_code(self) -> None:
        assert INTENT_CAPABILITY_MAP[IntentType.CODE_GEN] == ModelCapability.CODE

    def test_code_review_maps_to_code(self) -> None:
        assert INTENT_CAPABILITY_MAP[IntentType.CODE_REVIEW] == ModelCapability.CODE

    def test_debugging_maps_to_code(self) -> None:
        assert INTENT_CAPABILITY_MAP[IntentType.DEBUGGING] == ModelCapability.CODE

    def test_general_maps_to_chat(self) -> None:
        assert INTENT_CAPABILITY_MAP[IntentType.GENERAL] == ModelCapability.CHAT

    def test_docs_maps_to_chat(self) -> None:
        assert INTENT_CAPABILITY_MAP[IntentType.DOCS] == ModelCapability.CHAT

    def test_all_values_are_model_capability(self) -> None:
        for intent, cap in INTENT_CAPABILITY_MAP.items():
            assert isinstance(cap, ModelCapability), (
                f"{intent}: expected ModelCapability, got {type(cap)}"
            )


# ---------------------------------------------------------------------------
# Hot path — cache hit
# ---------------------------------------------------------------------------


class TestModelRouterCacheHit:
    @pytest.mark.asyncio
    async def test_returns_first_cached_score(self) -> None:
        scores = [_make_score("best-model", 0.9), _make_score("second-model", 0.5)]
        router, model_list_cache, _ = _make_router(scored_cache_return=scores)

        result = await router.select(IntentType.GENERAL)

        assert result is not None
        assert result.model_id == "best-model"

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_call_model_list_cache(self) -> None:
        scores = [_make_score("cached-model")]
        router, model_list_cache, _ = _make_router(scored_cache_return=scores)

        await router.select(IntentType.GENERAL)

        model_list_cache.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_call_scored_cache_set(self) -> None:
        scores = [_make_score("cached-model")]
        router, _, scored_model_cache = _make_router(scored_cache_return=scores)

        await router.select(IntentType.CODE_GEN)

        scored_model_cache.set.assert_not_called()


# ---------------------------------------------------------------------------
# Cold path — cache miss
# ---------------------------------------------------------------------------


class TestModelRouterCacheMiss:
    @pytest.mark.asyncio
    async def test_returns_highest_scoring_eligible_model(self) -> None:
        candidates = [
            _make_model(
                "cheap-fast",
                capabilities=[ModelCapability.CHAT],
                latency_tier=LatencyTier.FAST,
                cost_per_1k_tokens=0.001,
            ),
            _make_model(
                "expensive-slow",
                capabilities=[ModelCapability.CHAT],
                latency_tier=LatencyTier.SLOW,
                cost_per_1k_tokens=0.050,
            ),
        ]
        router, _, scored_model_cache = _make_router(list_cache_return=candidates)

        result = await router.select(IntentType.GENERAL)

        assert result is not None
        assert result.model_id in {"cheap-fast", "expensive-slow"}

    @pytest.mark.asyncio
    async def test_populates_scored_cache_on_miss(self) -> None:
        candidates = [_make_model("model-a", capabilities=[ModelCapability.CHAT])]
        router, _, scored_model_cache = _make_router(list_cache_return=candidates)

        await router.select(IntentType.GENERAL)

        scored_model_cache.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_populates_cache_with_sorted_scores(self) -> None:
        candidates = [
            _make_model(
                "slow-model",
                capabilities=[ModelCapability.CHAT],
                latency_tier=LatencyTier.SLOW,
                cost_per_1k_tokens=0.05,
            ),
            _make_model(
                "fast-model",
                capabilities=[ModelCapability.CHAT],
                latency_tier=LatencyTier.FAST,
                cost_per_1k_tokens=0.001,
            ),
        ]
        router, _, scored_model_cache = _make_router(list_cache_return=candidates)

        await router.select(IntentType.GENERAL)

        scored_model_cache.set.assert_awaited_once()
        _, scores_arg = scored_model_cache.set.call_args.args
        composites = [s.composite_score for s in scores_arg]
        assert composites == sorted(composites, reverse=True)

    @pytest.mark.asyncio
    async def test_cache_miss_calls_model_list_cache_get(self) -> None:
        candidates = [_make_model("model-a", capabilities=[ModelCapability.CHAT])]
        router, model_list_cache, _ = _make_router(list_cache_return=candidates)

        await router.select(IntentType.GENERAL)

        model_list_cache.get.assert_awaited_once()


# ---------------------------------------------------------------------------
# Empty / None model list cache
# ---------------------------------------------------------------------------


class TestModelRouterEmptyModelList:
    @pytest.mark.asyncio
    async def test_returns_none_when_model_list_cache_is_none(self) -> None:
        router, _, _ = _make_router(list_cache_return=None)

        result = await router.select(IntentType.GENERAL)

        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_set_scored_cache_when_model_list_none(self) -> None:
        router, _, scored_model_cache = _make_router(list_cache_return=None)

        await router.select(IntentType.GENERAL)

        scored_model_cache.set.assert_not_called()


# ---------------------------------------------------------------------------
# Capability filter
# ---------------------------------------------------------------------------


class TestModelRouterCapabilityFilter:
    @pytest.mark.asyncio
    async def test_filters_out_models_missing_required_capability(self) -> None:
        # code-gen requires ModelCapability.CODE; chat-only model must be excluded
        candidates = [
            _make_model("chat-only", capabilities=[ModelCapability.CHAT]),
            _make_model("code-model", capabilities=[ModelCapability.CHAT, ModelCapability.CODE]),
        ]
        router, _, _ = _make_router(list_cache_return=candidates)

        result = await router.select(IntentType.CODE_GEN)

        assert result is not None
        assert result.model_id == "code-model"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_eligible_models_after_filter(self) -> None:
        # All candidates are chat-only; code-gen requires CODE capability
        candidates = [
            _make_model("chat-a", capabilities=[ModelCapability.CHAT]),
            _make_model("chat-b", capabilities=[ModelCapability.CHAT]),
        ]
        router, _, _ = _make_router(list_cache_return=candidates)

        result = await router.select(IntentType.CODE_GEN)

        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_set_scored_cache_when_no_eligible_models(self) -> None:
        candidates = [_make_model("chat-only", capabilities=[ModelCapability.CHAT])]
        router, _, scored_model_cache = _make_router(list_cache_return=candidates)

        await router.select(IntentType.DEBUGGING)

        scored_model_cache.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_general_intent_accepts_chat_capable_model(self) -> None:
        candidates = [_make_model("chat-model", capabilities=[ModelCapability.CHAT])]
        router, _, _ = _make_router(list_cache_return=candidates)

        result = await router.select(IntentType.GENERAL)

        assert result is not None
        assert result.model_id == "chat-model"


# ---------------------------------------------------------------------------
# Weight override
# ---------------------------------------------------------------------------


class TestModelRouterWeightOverride:
    @pytest.mark.asyncio
    async def test_custom_weights_influence_ranking(self) -> None:
        # latency-focused weights should prefer FAST over SLOW models
        latency_focused = RoutingWeights(
            quality_weight=0.1,
            cost_weight=0.1,
            latency_weight=0.8,
        )
        candidates = [
            _make_model(
                "slow-model",
                capabilities=[ModelCapability.CHAT],
                latency_tier=LatencyTier.SLOW,
                cost_per_1k_tokens=0.05,
            ),
            _make_model(
                "fast-model",
                capabilities=[ModelCapability.CHAT],
                latency_tier=LatencyTier.FAST,
                cost_per_1k_tokens=0.001,
            ),
        ]
        router, _, _ = _make_router(list_cache_return=candidates)

        result = await router.select(IntentType.GENERAL, weights=latency_focused)

        assert result is not None
        assert result.model_id == "fast-model"

    @pytest.mark.asyncio
    async def test_weight_override_bypasses_default_table(self) -> None:
        custom_weights = RoutingWeights(
            quality_weight=0.8,
            cost_weight=0.1,
            latency_weight=0.1,
        )
        candidates = [_make_model("model-x", capabilities=[ModelCapability.CHAT], latency_tier=LatencyTier.SLOW)]
        router, _, scored_model_cache = _make_router(list_cache_return=candidates)

        await router.select(IntentType.GENERAL, weights=custom_weights)

        scored_model_cache.set.assert_awaited_once()
        _, scores_arg = scored_model_cache.set.call_args.args
        # With quality_weight=0.8, SLOW tier (quality=1.0) should dominate
        assert scores_arg[0].quality_score == 1.0
