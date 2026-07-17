from __future__ import annotations

import logging

from langfuse import Langfuse

from src.observability.cost.schemas import CompressionRecord, LLMCallRecord
from src.observability.cost.settings import LangfuseProjectSettings

logger = logging.getLogger(__name__)


class LLMCostRecorder:
    """
    Writes LLM call records and compression records to Langfuse (AC-1, AC-2, AC-4).

    Langfuse stores each record as a Generation / Event with all six AC-1 fields
    as metadata, making them queryable via the Langfuse API and dashboard (AC-4).

    Write pattern: fire-and-forget — both methods are synchronous wrappers
    around the Langfuse SDK's non-blocking flush queue. They do not await IO
    and add no latency to the main request path.
    """

    def __init__(self, settings: LangfuseProjectSettings | None = None) -> None:
        cfg = settings or LangfuseProjectSettings()
        self._langfuse = Langfuse(
            public_key=cfg.public_key,
            secret_key=cfg.secret_key,
            host=cfg.host,
        )

    def record_llm_call(self, record: LLMCallRecord) -> None:
        """
        AC-1: Write one LLM invocation to Langfuse as a Generation.
        All six AC-1 fields are included in `metadata` for Langfuse API
        queryability (AC-4).
        """
        try:
            self._langfuse.generation(
                id=str(record.request_id),
                name=f"llm-call/{record.model_id}",
                model=record.model_id,
                usage={
                    "promptTokens": record.prompt_tokens,
                    "completionTokens": record.completion_tokens,
                    "totalCost": record.cost_usd,
                },
                metadata={
                    # AC-1 required fields
                    "model_id": record.model_id,
                    "prompt_tokens": record.prompt_tokens,
                    "completion_tokens": record.completion_tokens,
                    "cost_usd": record.cost_usd,
                    "user_id": record.user_id,
                    "team_id": record.team_id,
                    # Supplementary
                    "tenant_id": record.tenant_id,
                    "intent_type": record.intent_type,
                },
                start_time=record.timestamp,
            )
        except Exception:
            logger.exception(
                "langfuse.record_llm_call failed request_id=%s", record.request_id
            )

    def record_compression(self, record: CompressionRecord) -> None:
        """
        AC-2: Write compression savings to Langfuse as a named event.
        """
        try:
            self._langfuse.event(
                name="compression_savings",
                metadata={
                    "request_id": str(record.request_id),
                    "user_id": record.user_id,
                    "team_id": record.team_id,
                    "tenant_id": record.tenant_id,
                    "intent_type": record.intent_type,
                    # AC-2 required fields
                    "tokens_before_compression": record.tokens_before_compression,
                    "tokens_after_compression": record.tokens_after_compression,
                    # Derived
                    "savings_tokens": record.savings_tokens,
                    "savings_pct": record.savings_pct,
                },
                start_time=record.timestamp,
            )
        except Exception:
            logger.exception(
                "langfuse.record_compression failed request_id=%s", record.request_id
            )

    def flush(self) -> None:
        """
        Flush the Langfuse SDK's internal queue.
        Called during lifespan shutdown to avoid losing buffered events.
        """
        self._langfuse.flush()
