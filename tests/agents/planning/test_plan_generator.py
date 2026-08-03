"""Unit tests for src/agents/planning/plan_generator.py (AIR-007 / TASK-US010-03)."""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from src.agents.planning.plan_generator import (
    CACHE_ELIGIBLE_INTENTS,
    RANKING_STRATEGY_MAP,
    generate_execution_plan,
)
from src.agents.schemas.execution_plan import RankingStrategy
from src.agents.schemas.intent import IntentType


class TestRankingStrategyMap:
    def test_all_eight_intent_types_covered(self) -> None:
        for intent in IntentType:
            assert intent in RANKING_STRATEGY_MAP, f"{intent} missing from RANKING_STRATEGY_MAP"

    def test_debugging_uses_hybrid(self) -> None:
        assert RANKING_STRATEGY_MAP[IntentType.DEBUGGING] == RankingStrategy.HYBRID

    def test_code_gen_uses_semantic(self) -> None:
        assert RANKING_STRATEGY_MAP[IntentType.CODE_GEN] == RankingStrategy.SEMANTIC

    def test_architecture_uses_semantic(self) -> None:
        assert RANKING_STRATEGY_MAP[IntentType.ARCHITECTURE] == RankingStrategy.SEMANTIC

    def test_docs_uses_semantic(self) -> None:
        assert RANKING_STRATEGY_MAP[IntentType.DOCS] == RankingStrategy.SEMANTIC

    def test_incident_uses_bm25(self) -> None:
        assert RANKING_STRATEGY_MAP[IntentType.INCIDENT] == RankingStrategy.BM25

    def test_metrics_uses_bm25(self) -> None:
        assert RANKING_STRATEGY_MAP[IntentType.METRICS] == RankingStrategy.BM25

    def test_code_review_uses_hybrid(self) -> None:
        assert RANKING_STRATEGY_MAP[IntentType.CODE_REVIEW] == RankingStrategy.HYBRID

    def test_general_uses_hybrid(self) -> None:
        assert RANKING_STRATEGY_MAP[IntentType.GENERAL] == RankingStrategy.HYBRID


class TestCacheEligibleIntents:
    def test_docs_is_cache_eligible(self) -> None:
        assert IntentType.DOCS in CACHE_ELIGIBLE_INTENTS

    def test_architecture_is_cache_eligible(self) -> None:
        assert IntentType.ARCHITECTURE in CACHE_ELIGIBLE_INTENTS

    def test_code_gen_is_cache_eligible(self) -> None:
        assert IntentType.CODE_GEN in CACHE_ELIGIBLE_INTENTS

    def test_incident_is_not_cache_eligible(self) -> None:
        assert IntentType.INCIDENT not in CACHE_ELIGIBLE_INTENTS

    def test_debugging_is_not_cache_eligible(self) -> None:
        assert IntentType.DEBUGGING not in CACHE_ELIGIBLE_INTENTS

    def test_general_is_not_cache_eligible(self) -> None:
        assert IntentType.GENERAL not in CACHE_ELIGIBLE_INTENTS

    def test_metrics_is_not_cache_eligible(self) -> None:
        assert IntentType.METRICS not in CACHE_ELIGIBLE_INTENTS

    def test_code_review_is_not_cache_eligible(self) -> None:
        assert IntentType.CODE_REVIEW not in CACHE_ELIGIBLE_INTENTS


class TestGenerateExecutionPlanAcceptanceCriteria:
    def test_incident_returns_bm25_not_cache_eligible(self) -> None:
        plan = generate_execution_plan(
            IntentType.INCIDENT, 0.9, ["grafana", "jira", "pagerduty"]
        )
        assert plan.ranking_strategy == RankingStrategy.BM25
        assert plan.cache_eligible is False

    def test_docs_returns_semantic_and_cache_eligible(self) -> None:
        plan = generate_execution_plan(IntentType.DOCS, 0.85, ["confluence", "github"])
        assert plan.ranking_strategy == RankingStrategy.SEMANTIC
        assert plan.cache_eligible is True

    def test_token_budget_per_source_keys_match_sources(self) -> None:
        sources = ["grafana", "jira", "pagerduty"]
        plan = generate_execution_plan(IntentType.INCIDENT, 0.9, sources)
        assert set(plan.token_budget_per_source.keys()) == set(sources)

    def test_token_budget_per_source_no_orphan_keys(self) -> None:
        sources = ["confluence", "github"]
        plan = generate_execution_plan(IntentType.DOCS, 0.85, sources)
        assert set(plan.token_budget_per_source.keys()) == set(sources)


class TestGenerateExecutionPlanAllIntents:
    @pytest.mark.parametrize(
        ("intent_type", "expected_strategy", "expected_cache"),
        [
            (IntentType.DEBUGGING, RankingStrategy.HYBRID, False),
            (IntentType.CODE_GEN, RankingStrategy.SEMANTIC, True),
            (IntentType.ARCHITECTURE, RankingStrategy.SEMANTIC, True),
            (IntentType.DOCS, RankingStrategy.SEMANTIC, True),
            (IntentType.INCIDENT, RankingStrategy.BM25, False),
            (IntentType.METRICS, RankingStrategy.BM25, False),
            (IntentType.CODE_REVIEW, RankingStrategy.HYBRID, False),
            (IntentType.GENERAL, RankingStrategy.HYBRID, False),
        ],
    )
    def test_ranking_strategy_and_cache_eligibility(
        self,
        intent_type: IntentType,
        expected_strategy: RankingStrategy,
        expected_cache: bool,
    ) -> None:
        plan = generate_execution_plan(intent_type, 0.9, ["github"])
        assert plan.ranking_strategy == expected_strategy
        assert plan.cache_eligible is expected_cache

    def test_sources_propagated_to_plan(self) -> None:
        sources = ["github", "confluence", "jira"]
        plan = generate_execution_plan(IntentType.DEBUGGING, 0.88, sources)
        assert plan.sources == sources

    def test_default_total_budget_used_when_not_specified(self) -> None:
        plan = generate_execution_plan(IntentType.GENERAL, 0.75, ["github"])
        assert plan.token_budget_total == 8_000

    def test_custom_total_budget_respected(self) -> None:
        plan = generate_execution_plan(IntentType.GENERAL, 0.75, ["github"], total_budget=16_000)
        assert plan.token_budget_total == 16_000

    def test_empty_source_list_produces_empty_budget(self) -> None:
        plan = generate_execution_plan(IntentType.GENERAL, 0.75, [])
        assert plan.sources == []
        assert plan.token_budget_per_source == {}

    def test_plan_is_immutable(self) -> None:
        plan = generate_execution_plan(IntentType.CODE_GEN, 0.9, ["github"])
        with pytest.raises((TypeError, ValidationError)):
            plan.sources = ["other"]  # type: ignore[misc]


class TestGenerateExecutionPlanBenchmark:
    def test_completes_under_1ms_for_all_intent_types(self) -> None:
        """generate_execution_plan() must complete in < 1 ms for all 8 intent types."""
        sources = ["github", "confluence", "jira"]
        for intent in IntentType:
            start = time.perf_counter()
            generate_execution_plan(intent, 0.9, sources)
            elapsed_ms = (time.perf_counter() - start) * 1000
            assert elapsed_ms < 1.0, (
                f"generate_execution_plan({intent}) took {elapsed_ms:.3f} ms, expected < 1 ms"
            )
