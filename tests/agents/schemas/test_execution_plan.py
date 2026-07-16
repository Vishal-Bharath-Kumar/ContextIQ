"""Unit tests for ExecutionPlan Pydantic schema (TASK-US010-01)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.agents.schemas.execution_plan import ExecutionPlan, RankingStrategy

VALID_PLAN = {
    "sources": ["github", "confluence"],
    "token_budget_total": 8_000,
    "token_budget_per_source": {"github": 4_000, "confluence": 4_000},
    "ranking_strategy": RankingStrategy.HYBRID,
    "cache_eligible": True,
}


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_valid_construction() -> None:
    plan = ExecutionPlan(**VALID_PLAN)
    assert plan.sources == ["github", "confluence"]
    assert plan.token_budget_total == 8_000
    assert plan.ranking_strategy == RankingStrategy.HYBRID
    assert plan.cache_eligible is True


def test_default_token_budget_total() -> None:
    plan = ExecutionPlan(
        sources=["github"],
        token_budget_per_source={"github": 8_000},
        ranking_strategy=RankingStrategy.SEMANTIC,
        cache_eligible=False,
    )
    assert plan.token_budget_total == 8_000


# ---------------------------------------------------------------------------
# token_budget_total validation
# ---------------------------------------------------------------------------


def test_token_budget_total_below_minimum_raises() -> None:
    with pytest.raises(ValidationError):
        ExecutionPlan(
            sources=["github"],
            token_budget_total=999,
            token_budget_per_source={"github": 999},
            ranking_strategy=RankingStrategy.SEMANTIC,
            cache_eligible=False,
        )


def test_token_budget_total_above_maximum_raises() -> None:
    with pytest.raises(ValidationError):
        ExecutionPlan(
            sources=["github"],
            token_budget_total=32_001,
            token_budget_per_source={"github": 32_001},
            ranking_strategy=RankingStrategy.SEMANTIC,
            cache_eligible=False,
        )


def test_token_budget_total_at_minimum_boundary() -> None:
    plan = ExecutionPlan(
        sources=["github"],
        token_budget_total=1_000,
        token_budget_per_source={"github": 1_000},
        ranking_strategy=RankingStrategy.BM25,
        cache_eligible=True,
    )
    assert plan.token_budget_total == 1_000


def test_token_budget_total_at_maximum_boundary() -> None:
    plan = ExecutionPlan(
        sources=["github"],
        token_budget_total=32_000,
        token_budget_per_source={"github": 32_000},
        ranking_strategy=RankingStrategy.BM25,
        cache_eligible=False,
    )
    assert plan.token_budget_total == 32_000


# ---------------------------------------------------------------------------
# model_dump round-trip
# ---------------------------------------------------------------------------


def test_model_dump_is_json_serialisable() -> None:
    plan = ExecutionPlan(**VALID_PLAN)
    dumped = plan.model_dump()
    serialised = json.dumps(dumped)  # must not raise
    reloaded = json.loads(serialised)
    assert reloaded["sources"] == ["github", "confluence"]
    assert reloaded["ranking_strategy"] == "hybrid"
    assert reloaded["cache_eligible"] is True


def test_model_dump_contains_no_custom_types() -> None:
    plan = ExecutionPlan(**VALID_PLAN)
    dumped = plan.model_dump()
    for value in dumped.values():
        assert not hasattr(value, "__class__") or isinstance(
            value, (str, int, float, bool, list, dict, type(None))
        )


# ---------------------------------------------------------------------------
# Immutability (frozen=True)
# ---------------------------------------------------------------------------


def test_mutation_raises_validation_error() -> None:
    plan = ExecutionPlan(**VALID_PLAN)
    with pytest.raises((ValidationError, TypeError)):
        plan.cache_eligible = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RankingStrategy enum values
# ---------------------------------------------------------------------------


def test_ranking_strategy_values() -> None:
    assert RankingStrategy.SEMANTIC == "semantic"
    assert RankingStrategy.BM25 == "bm25"
    assert RankingStrategy.HYBRID == "hybrid"
