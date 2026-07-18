import litellm

from src.model_invoker.config import LATENCY_TIER_TIMEOUT, InvokerSettings
from src.model_invoker.schemas.llm_response import LLMResponse
from src.model_registry.schemas.model_definition import LatencyTier


class LiteLLMInvoker:
    def __init__(self, settings: InvokerSettings | None = None) -> None:
        self._settings = settings or InvokerSettings()
        LATENCY_TIER_TIMEOUT.update(
            {
                LatencyTier.FAST: self._settings.timeout_fast_s,
                LatencyTier.MEDIUM: self._settings.timeout_medium_s,
                LatencyTier.SLOW: self._settings.timeout_slow_s,
            }
        )

    async def invoke(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        token_budget: int,
        latency_tier: LatencyTier = LatencyTier.MEDIUM,
        callbacks: list | None = None,
    ) -> LLMResponse:
        timeout = LATENCY_TIER_TIMEOUT[latency_tier]

        response = await litellm.acompletion(
            model=model_id,
            messages=messages,
            max_tokens=token_budget,
            timeout=timeout,
            callbacks=callbacks or [],
        )

        choice = response.choices[0]
        usage = response.usage

        return LLMResponse(
            model_id=model_id,
            content=choice.message.content or "",
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            finish_reason=choice.finish_reason or "stop",
        )
