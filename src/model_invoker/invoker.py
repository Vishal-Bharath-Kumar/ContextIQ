import litellm
from langfuse import Langfuse

from src.model_invoker.config import LATENCY_TIER_TIMEOUT, InvokerSettings
from src.model_invoker.schemas.llm_response import LLMResponse
from src.model_registry.schemas.model_definition import LatencyTier
from src.observability.langfuse_integration import get_litellm_callback, get_langfuse


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
        
        # Get Langfuse callback for LiteLLM tracing
        # LiteLLM accepts "langfuse" as a string callback name
        langfuse_callback = get_litellm_callback()
        self._default_callbacks = [langfuse_callback] if langfuse_callback else []

    async def invoke(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        token_budget: int,
        latency_tier: LatencyTier = LatencyTier.MEDIUM,
        callbacks: list | None = None,
    ) -> LLMResponse:
        timeout = LATENCY_TIER_TIMEOUT[latency_tier]
        
        # Merge default Langfuse callback with any provided callbacks
        all_callbacks = self._default_callbacks + (callbacks or [])

        response = await litellm.acompletion(
            model=model_id,
            messages=messages,
            max_tokens=token_budget,
            timeout=timeout,
            callbacks=all_callbacks,
        )

        choice = response.choices[0]
        usage = response.usage

        # Manually create Langfuse generation via REST API (SDK has data persistence bug)
        # Using ingestion endpoint for async batch processing
        langfuse_client = get_langfuse()
        if langfuse_client:
            try:
                import requests
                import uuid
                from datetime import datetime, UTC
                from src.observability.langfuse_integration.settings import LangfuseSettings
                
                settings = LangfuseSettings()
                if not settings.is_configured:
                    return
                
                # Generate IDs
                trace_id = str(uuid.uuid4())
                observation_id = str(uuid.uuid4())
                now = datetime.now(UTC).isoformat()
                
                # Use the ingestion batch API
                batch_data = {
                    "batch": [
                        {
                            "id": trace_id,
                            "type": "trace-create",
                            "timestamp": now,
                            "body": {
                                "id": trace_id,
                                "name": "llm-invocation",
                                "timestamp": now,
                                "input": messages,
                                "output": choice.message.content or "",
                                "metadata": {"model": model_id, "latency_tier": latency_tier.value},
                            }
                        },
                        {
                            "id": observation_id,
                            "type": "observation-create",
                            "timestamp": now,
                            "body": {
                                "id": observation_id,
                                "traceId": trace_id,
                                "type": "GENERATION",
                                "name": "llm-generation",
                                "startTime": now,
                                "endTime": now,
                                "model": model_id,
                                "modelParameters": {"max_tokens": token_budget},
                                "input": messages,
                                "output": choice.message.content or "",
                                "usage": {
                                    "promptTokens": usage.prompt_tokens,
                                    "completionTokens": usage.completion_tokens,
                                    "totalTokens": usage.total_tokens,
                                },
                                "metadata": {
                                    "latency_tier": latency_tier.value,
                                    "finish_reason": choice.finish_reason or "stop",
                                },
                            }
                        }
                    ],
                    "metadata": {"sdk_name": "python-custom", "sdk_version": "1.0.0"}
                }
                
                resp = requests.post(
                    f"{settings.base_url}/api/public/ingestion",
                    auth=(settings.public_key, settings.secret_key),
                    json=batch_data,
                    timeout=5,
                )
                
                if resp.status_code not in (200, 207):
                    print(f"[LANGFUSE] Ingestion failed: {resp.status_code} - {resp.text[:300]}")
            except Exception as e:
                # Silently fail to avoid disrupting LLM calls
                pass

        return LLMResponse(
            model_id=model_id,
            content=choice.message.content or "",
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            finish_reason=choice.finish_reason or "stop",
        )
