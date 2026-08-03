"""FallbackInvoker: retry orchestration with circuit breaker (TASK-US020-04)."""

from __future__ import annotations

import logging

from src.model_invoker.circuit_breaker import ProviderCircuitBreaker
from src.model_invoker.config import InvokerSettings
from src.model_invoker.error_classifier import classify_error, extract_provider
from src.model_invoker.invoker import LiteLLMInvoker
from src.model_invoker.schemas.fallback_chain import FallbackChain, InvocationFailure
from src.model_invoker.schemas.fallback_event import FallbackEvent
from src.model_invoker.schemas.llm_response import LLMResponse
from src.model_registry.schemas.model_definition import LatencyTier

_log = logging.getLogger(__name__)


class FallbackInvoker:
    """Wraps LiteLLMInvoker and orchestrates retries across an ordered FallbackChain.

    Checks the ProviderCircuitBreaker before each attempt, catches retryable
    errors, emits FallbackEvent log records, and returns InvocationFailure when
    the chain is exhausted.  The fallback path adds ≤ 500 ms per retry (US-020 AC-6).
    """

    def __init__(
        self,
        invoker: LiteLLMInvoker,
        circuit_breaker: ProviderCircuitBreaker,
        settings: InvokerSettings | None = None,
    ) -> None:
        self._invoker = invoker
        self._circuit_breaker = circuit_breaker
        self._settings = settings or InvokerSettings()

    async def invoke(
        self,
        fallback_chain: FallbackChain,
        messages: list[dict[str, str]],
        token_budget: int,
        latency_tier: LatencyTier = LatencyTier.MEDIUM,
        callbacks: list | None = None,
    ) -> LLMResponse | InvocationFailure:
        """Iterate the fallback chain, returning the first successful LLMResponse.

        Returns InvocationFailure when every candidate has been tried (or skipped
        due to an open circuit) and none succeeded.
        """
        max_attempts = self._settings.max_fallback_attempts + 1  # primary + N fallbacks
        tried: list[str] = []
        last_error_code = "unknown"

        for model_id in fallback_chain.model_ids[:max_attempts]:
            provider = extract_provider(model_id)

            if not await self._circuit_breaker.is_available(provider):
                _log.warning(
                    "circuit_breaker_open",
                    extra={"model_id": model_id, "provider": provider},
                )
                tried.append(model_id)
                continue  # skip — open circuit counts against budget; move to next candidate

            try:
                response = await self._invoker.invoke(
                    model_id=model_id,
                    messages=messages,
                    token_budget=token_budget,
                    latency_tier=latency_tier,
                    callbacks=callbacks,
                )
                await self._circuit_breaker.record_success(provider)
                return response

            except Exception as exc:  # noqa: BLE001
                error_code = classify_error(exc)

                if error_code is None:
                    # Non-retryable (auth, bad request, context window) — re-raise immediately.
                    # No fallback, no circuit-breaker recording, no FallbackEvent.
                    raise

                await self._circuit_breaker.record_failure(provider)
                tried.append(model_id)
                last_error_code = error_code.value

                # Determine the next candidate for the FallbackEvent log (None if exhausted).
                next_idx = fallback_chain.model_ids.index(model_id) + 1
                next_model_id: str | None = (
                    fallback_chain.model_ids[next_idx]
                    if next_idx < len(fallback_chain.model_ids)
                    else None
                )
                attempt_number = len(tried)

                event = FallbackEvent(
                    attempt=attempt_number,
                    primary_model_id=model_id,
                    error_code=error_code,
                    fallback_model_id=next_model_id,
                    provider=provider,
                )
                _log.warning("fallback_attempt", extra=event.model_dump())

        return InvocationFailure(
            message=(
                f"All {len(tried)} model(s) in the fallback chain failed. "
                f"Last error: {last_error_code}."
            ),
            attempts=len(tried),
            last_error_code=last_error_code,
            tried_model_ids=tried,
        )
