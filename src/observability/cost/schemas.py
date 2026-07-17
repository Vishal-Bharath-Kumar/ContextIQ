from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LLMCallRecord(BaseModel):
    """
    Single LLM invocation record written to Langfuse (AC-1).

    Required fields per AC-1:
      model_id, prompt_tokens, completion_tokens, cost_usd, user_id, team_id
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    request_id: UUID
    tenant_id: str

    # AC-1 required fields
    model_id: str = Field(description="LiteLLM model string, e.g. 'gpt-4o'.")
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0, description="Cost in USD computed by LiteLLM cost map.")
    user_id: str = Field(description="JWT sub claim.")
    team_id: str = Field(description="Team extracted from JWT claims or default group.")

    # Supplementary fields for Grafana grouping (AC-3, AC-6)
    intent_type: str = "unknown"
    timestamp: datetime


class CompressionRecord(BaseModel):
    """
    Compression savings record written to Langfuse (AC-2).
    Also used to populate Prometheus compression metrics (TASK-US037-02).
    """

    model_config = ConfigDict(frozen=True)

    request_id: UUID
    tenant_id: str
    user_id: str
    team_id: str
    intent_type: str = "unknown"
    timestamp: datetime

    # AC-2 required fields
    tokens_before_compression: int = Field(ge=0)
    tokens_after_compression: int = Field(ge=0)

    @property
    def savings_tokens(self) -> int:
        return max(0, self.tokens_before_compression - self.tokens_after_compression)

    @property
    def savings_pct(self) -> float:
        if self.tokens_before_compression == 0:
            return 0.0
        return round(
            100 * self.savings_tokens / self.tokens_before_compression, 2
        )
