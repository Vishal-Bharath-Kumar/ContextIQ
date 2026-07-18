"""Unit tests for ModelRouter.build_fallback_chain() and FallbackChain schema (TASK-US020-01)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from src.model_invoker.config import InvokerSettings
from src.model_invoker.schemas.fallback_chain import FallbackChain, InvocationFailure
from src.model_router.router import ModelRouter
from src.model_router.schemas.model_score import ModelScore

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make_score(model_id: str, composite: float = 0.75) -> ModelScore:
    return ModelScore(
        model_id=model_id,
        quality_score=0.6,
        normalised_cost=500.0,
        normalised_latency=1.0,
        composite_score=composite,
    )


_SENTINEL = object()


def _make_router(
    scored_cache_return: list[ModelScore] | None = None,
    scored_cache_after_select: list[ModelScore] | None | object = _SENTINEL,
) -> tuple[ModelRouter, AsyncMock, AsyncMock]:
    """Build a ModelRouter with fully mocked caches.

    ``scored_cache_return`` is the value returned by the *first* ``get()`` call
    (from ``build_fallback_chain``).

    ``scored_cache_after_select`` is returned by the *third* ``get()`` call
    (the re-read after ``select()`` populates the cache on the cold path).
    When not provided, all calls return ``scored_cache_return``.

    Note: ``select()`` internally makes a *second* ``get()`` call, so the
    side-effect list must contain 3 entries for cold-path scenarios.
    """
    model_list_cache = AsyncMock()
    model_list_cache.get = AsyncMock(return_value=None)

    scored_model_cache = AsyncMock()

    if scored_cache_after_select is not _SENTINEL:
        # Three calls expected:
        # 1. build_fallback_chain initial get → scored_cache_return (None = cold miss)
        # 2. select() internal get            → scored_cache_return (still cold)
        # 3. build_fallback_chain post-select → scored_cache_after_select
        scored_model_cache.get = AsyncMock(
            side_effect=[scored_cache_return, scored_cache_return, scored_cache_after_select]
        )
    else:
        scored_model_cache.get = AsyncMock(return_value=scored_cache_return)

    scored_model_cache.set = AsyncMock()

    router = ModelRouter(
        model_list_cache=model_list_cache,
        scored_model_cache=scored_model_cache,
    )
    return router, model_list_cache, scored_model_cache


# ---------------------------------------------------------------------------
# FallbackChain schema validation
# ---------------------------------------------------------------------------


class TestFallbackChainSchema:
    def test_valid_chain(self) -> None:
        chain = FallbackChain(model_ids=["gpt-4o", "claude-3"], intent_type="general")
        assert chain.model_ids == ["gpt-4o", "claude-3"]
        assert chain.intent_type == "general"

    def test_empty_model_ids_raises(self) -> None:
        with pytest.raises(ValidationError):
            FallbackChain(model_ids=[], intent_type="general")

    def test_frozen_immutability(self) -> None:
        chain = FallbackChain(model_ids=["gpt-4o"], intent_type="general")
        with pytest.raises(ValidationError):
            chain.model_ids = ["other-model"]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# InvocationFailure schema validation
# ---------------------------------------------------------------------------


class TestInvocationFailureSchema:
    def test_valid_failure(self) -> None:
        failure = InvocationFailure(
            message="All fallback attempts exhausted",
            attempts=4,
            last_error_code="TIMEOUT",
            tried_model_ids=["gpt-4o", "claude-3", "gemini-pro", "llama-3"],
        )
        assert failure.attempts == 4
        assert failure.last_error_code == "TIMEOUT"

    def test_frozen_immutability(self) -> None:
        failure = InvocationFailure(
            message="error",
            attempts=1,
            last_error_code="RATE_LIMIT",
            tried_model_ids=["gpt-4o"],
        )
        with pytest.raises(ValidationError):
            failure.attempts = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# InvokerSettings defaults
# ---------------------------------------------------------------------------


class TestInvokerSettings:
    def test_default_max_fallback_attempts(self) -> None:
        settings = InvokerSettings()
        assert settings.max_fallback_attempts == 3

    def test_default_fallback_chain_size(self) -> None:
        settings = InvokerSettings()
        assert settings.fallback_chain_size == 4

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INVOKER_MAX_FALLBACK_ATTEMPTS", "5")
        settings = InvokerSettings()
        assert settings.max_fallback_attempts == 5


# ---------------------------------------------------------------------------
# ModelRouter.build_fallback_chain() — hot path (cache populated)
# ---------------------------------------------------------------------------


class TestBuildFallbackChainHotPath:
    @pytest.mark.asyncio
    async def test_returns_chain_from_cache(self) -> None:
        scores = [_make_score(f"model-{i}", composite=1.0 - i * 0.1) for i in range(5)]
        router, _, _ = _make_router(scored_cache_return=scores)

        chain = await router.build_fallback_chain(intent_type="general")

        assert chain is not None
        assert len(chain.model_ids) == 4  # default fallback_chain_size
        assert chain.model_ids[0] == "model-0"

    @pytest.mark.asyncio
    async def test_chain_truncated_to_fallback_chain_size(self) -> None:
        scores = [_make_score(f"model-{i}") for i in range(10)]
        router, _, _ = _make_router(scored_cache_return=scores)
        settings = InvokerSettings(fallback_chain_size=2)

        chain = await router.build_fallback_chain(intent_type="general", settings=settings)

        assert chain is not None
        assert len(chain.model_ids) == 2

    @pytest.mark.asyncio
    async def test_chain_size_does_not_exceed_available_candidates(self) -> None:
        scores = [_make_score("model-0"), _make_score("model-1")]
        router, _, _ = _make_router(scored_cache_return=scores)
        settings = InvokerSettings(fallback_chain_size=4)

        chain = await router.build_fallback_chain(intent_type="general", settings=settings)

        assert chain is not None
        assert len(chain.model_ids) == 2  # only 2 candidates available

    @pytest.mark.asyncio
    async def test_intent_type_propagated(self) -> None:
        scores = [_make_score("gpt-4o")]
        router, _, _ = _make_router(scored_cache_return=scores)

        chain = await router.build_fallback_chain(intent_type="code_gen")

        assert chain is not None
        assert chain.intent_type == "code_gen"


# ---------------------------------------------------------------------------
# ModelRouter.build_fallback_chain() — cold path (cache miss → select())
# ---------------------------------------------------------------------------


class TestBuildFallbackChainColdPath:
    @pytest.mark.asyncio
    async def test_cold_path_populates_cache_via_select(self) -> None:
        scores = [_make_score(f"model-{i}", composite=1.0 - i * 0.1) for i in range(4)]
        # First get() → None (cold); second (inside select) → None; third (post-select) → scores
        router, _, scored_cache = _make_router(
            scored_cache_return=None,
            scored_cache_after_select=scores,
        )

        chain = await router.build_fallback_chain(intent_type="general")

        # Verify get() was called 3 times (initial, select-internal, post-select re-read)
        assert scored_cache.get.call_count == 3
        assert chain is not None
        assert chain.model_ids[0] == "model-0"

    @pytest.mark.asyncio
    async def test_cold_path_empty_after_select_returns_none(self) -> None:
        # All get() calls return None (no candidates ever)
        router, _, scored_cache = _make_router(
            scored_cache_return=None,
            scored_cache_after_select=None,
        )

        chain = await router.build_fallback_chain(intent_type="general")

        assert chain is None

    @pytest.mark.asyncio
    async def test_cold_path_empty_list_after_select_returns_none(self) -> None:
        # First/second get() → None; third (post-select re-read) → empty list
        router, _, _ = _make_router(
            scored_cache_return=None,
            scored_cache_after_select=[],
        )

        chain = await router.build_fallback_chain(intent_type="general")

        assert chain is None


# ---------------------------------------------------------------------------
# ModelRouter.build_fallback_chain() — empty cache returns None
# ---------------------------------------------------------------------------


class TestBuildFallbackChainEmpty:
    @pytest.mark.asyncio
    async def test_empty_scored_list_returns_none(self) -> None:
        router, _, _ = _make_router(scored_cache_return=[])

        chain = await router.build_fallback_chain(intent_type="general")

        assert chain is None

    @pytest.mark.asyncio
    async def test_none_scored_cache_cold_path_returns_none(self) -> None:
        router, _, _ = _make_router(
            scored_cache_return=None,
            scored_cache_after_select=None,
        )

        chain = await router.build_fallback_chain(intent_type="general")

        assert chain is None
