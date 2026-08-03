"""Unit tests for LiteLLMInvoker (TASK-US019-05).

All tests use AsyncMock to patch litellm.acompletion — no live LLM calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.model_invoker.config import InvokerSettings
from src.model_invoker.invoker import LiteLLMInvoker
from src.model_invoker.schemas.llm_response import LLMResponse
from src.model_registry.schemas.model_definition import LatencyTier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MESSAGES = [{"role": "user", "content": "Hello, world!"}]
_MODEL_ID = "gpt-4o-mini"


def _make_litellm_response(
    content: str = "Hi there!",
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
    finish_reason: str = "stop",
) -> SimpleNamespace:
    """Build a minimal fake LiteLLM response object."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


# ---------------------------------------------------------------------------
# LLMResponse schema
# ---------------------------------------------------------------------------


class TestLLMResponse:
    def test_frozen_prevents_mutation(self) -> None:
        resp = LLMResponse(
            model_id=_MODEL_ID,
            content="hello",
            input_tokens=5,
            output_tokens=10,
            finish_reason="stop",
        )
        with pytest.raises((TypeError, ValueError)):
            resp.content = "modified"  # type: ignore[misc]

    def test_fields_accessible(self) -> None:
        resp = LLMResponse(
            model_id=_MODEL_ID,
            content="text",
            input_tokens=1,
            output_tokens=2,
            finish_reason="length",
        )
        assert resp.model_id == _MODEL_ID
        assert resp.finish_reason == "length"


# ---------------------------------------------------------------------------
# LiteLLMInvoker — successful invocation
# ---------------------------------------------------------------------------


class TestLiteLLMInvokerSuccessfulInvocation:
    @pytest.mark.asyncio
    async def test_returns_llm_response(self) -> None:
        fake_response = _make_litellm_response()
        settings = InvokerSettings(
            timeout_fast_s=10.0,
            timeout_medium_s=30.0,
            timeout_slow_s=120.0,
        )
        invoker = LiteLLMInvoker(settings=settings)

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = fake_response
            result = await invoker.invoke(
                model_id=_MODEL_ID,
                messages=_MESSAGES,
                token_budget=100,
            )

        assert isinstance(result, LLMResponse)
        assert result.model_id == _MODEL_ID
        assert result.content == "Hi there!"
        assert result.input_tokens == 10
        assert result.output_tokens == 20
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_token_counts_match_usage_object(self) -> None:
        fake_response = _make_litellm_response(
            prompt_tokens=42, completion_tokens=17
        )
        invoker = LiteLLMInvoker(settings=InvokerSettings())

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = fake_response
            result = await invoker.invoke(
                model_id=_MODEL_ID,
                messages=_MESSAGES,
                token_budget=50,
            )

        assert result.input_tokens == 42
        assert result.output_tokens == 17

    @pytest.mark.asyncio
    async def test_finish_reason_length_on_token_overflow(self) -> None:
        fake_response = _make_litellm_response(finish_reason="length")
        invoker = LiteLLMInvoker(settings=InvokerSettings())

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = fake_response
            result = await invoker.invoke(
                model_id=_MODEL_ID,
                messages=_MESSAGES,
                token_budget=5,
            )

        assert result.finish_reason == "length"

    @pytest.mark.asyncio
    async def test_null_content_becomes_empty_string(self) -> None:
        fake_response = _make_litellm_response(content=None)  # type: ignore[arg-type]
        invoker = LiteLLMInvoker(settings=InvokerSettings())

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = fake_response
            result = await invoker.invoke(
                model_id=_MODEL_ID,
                messages=_MESSAGES,
                token_budget=10,
            )

        assert result.content == ""

    @pytest.mark.asyncio
    async def test_null_finish_reason_defaults_to_stop(self) -> None:
        fake_response = _make_litellm_response(finish_reason=None)  # type: ignore[arg-type]
        invoker = LiteLLMInvoker(settings=InvokerSettings())

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = fake_response
            result = await invoker.invoke(
                model_id=_MODEL_ID,
                messages=_MESSAGES,
                token_budget=10,
            )

        assert result.finish_reason == "stop"


# ---------------------------------------------------------------------------
# LiteLLMInvoker — timeout mapped correctly per LatencyTier
# ---------------------------------------------------------------------------


class TestLiteLLMInvokerTimeoutMapping:
    def _make_invoker_with_settings(
        self,
        fast: float = 5.0,
        medium: float = 15.0,
        slow: float = 60.0,
    ) -> LiteLLMInvoker:
        return LiteLLMInvoker(
            settings=InvokerSettings(
                timeout_fast_s=fast,
                timeout_medium_s=medium,
                timeout_slow_s=slow,
            )
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "latency_tier,expected_timeout",
        [
            (LatencyTier.FAST, 5.0),
            (LatencyTier.MEDIUM, 15.0),
            (LatencyTier.SLOW, 60.0),
        ],
    )
    async def test_timeout_forwarded_for_each_tier(
        self, latency_tier: LatencyTier, expected_timeout: float
    ) -> None:
        invoker = self._make_invoker_with_settings()
        fake_response = _make_litellm_response()

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = fake_response
            await invoker.invoke(
                model_id=_MODEL_ID,
                messages=_MESSAGES,
                token_budget=10,
                latency_tier=latency_tier,
            )

        _, kwargs = mock_acompletion.call_args
        assert kwargs["timeout"] == expected_timeout

    def test_fast_timeout_shorter_than_slow(self) -> None:
        self._make_invoker_with_settings()
        from src.model_invoker.config import LATENCY_TIER_TIMEOUT

        assert LATENCY_TIER_TIMEOUT[LatencyTier.FAST] < LATENCY_TIER_TIMEOUT[LatencyTier.SLOW]


# ---------------------------------------------------------------------------
# LiteLLMInvoker — callbacks forwarded
# ---------------------------------------------------------------------------


class TestLiteLLMInvokerCallbacks:
    @pytest.mark.asyncio
    async def test_callbacks_forwarded_to_acompletion(self) -> None:
        fake_response = _make_litellm_response()
        invoker = LiteLLMInvoker(settings=InvokerSettings())
        fake_handler = object()

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = fake_response
            await invoker.invoke(
                model_id=_MODEL_ID,
                messages=_MESSAGES,
                token_budget=10,
                callbacks=[fake_handler],
            )

        _, kwargs = mock_acompletion.call_args
        assert kwargs["callbacks"] == [fake_handler]

    @pytest.mark.asyncio
    async def test_none_callbacks_becomes_empty_list(self) -> None:
        fake_response = _make_litellm_response()
        invoker = LiteLLMInvoker(settings=InvokerSettings())

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = fake_response
            await invoker.invoke(
                model_id=_MODEL_ID,
                messages=_MESSAGES,
                token_budget=10,
                callbacks=None,
            )

        _, kwargs = mock_acompletion.call_args
        assert kwargs["callbacks"] == []

    @pytest.mark.asyncio
    async def test_no_api_keys_logged_or_accessed(self) -> None:
        """Invoker must not reference any API key environment variables."""
        import inspect

        from src.model_invoker import invoker as invoker_module

        source = inspect.getsource(invoker_module)
        for key_suffix in ("_API_KEY", "_SECRET", "_TOKEN"):
            assert key_suffix not in source
