"""ExecutionPlan Pydantic schema for the ContextIQ pipeline (EP-003 / US-010)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RankingStrategy(StrEnum):
    SEMANTIC = "semantic"  # dense vector similarity (default for code-gen, docs, architecture)
    BM25 = "bm25"  # keyword/lexical (metrics, incident — exact metric names matter)
    HYBRID = "hybrid"  # weighted blend (general, debugging, code-review)


class ExecutionPlan(BaseModel):
    sources: list[str]  # ordered connector IDs to query (from AIR-006 mapping)
    token_budget_total: int = Field(default=8_000, ge=1_000, le=32_000)
    token_budget_per_source: dict[str, int]  # source_id → allocated token quota
    ranking_strategy: RankingStrategy  # retrieval ranking algorithm
    cache_eligible: bool  # whether plan result may be served from Redis cache

    model_config = ConfigDict(frozen=True)  # immutable once generated
