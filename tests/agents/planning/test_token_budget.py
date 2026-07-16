"""Unit tests for src/agents/planning/token_budget.py (AIR-009 / TASK-US010-02)."""

from __future__ import annotations

from src.agents.planning.token_budget import (
    DEFAULT_TOTAL_BUDGET,
    SOURCE_WEIGHT_TABLE,
    allocate_token_budget,
)
from src.agents.schemas.intent import IntentType


class TestAllocateTokenBudgetEmpty:
    def test_empty_source_list_returns_empty_dict(self) -> None:
        result = allocate_token_budget(IntentType.GENERAL, [], 8_000)
        assert result == {}

    def test_empty_source_list_any_intent_returns_empty_dict(self) -> None:
        for intent in IntentType:
            assert allocate_token_budget(intent, [], 8_000) == {}


class TestAllocateTokenBudgetSingleSource:
    def test_single_source_receives_total_budget(self) -> None:
        result = allocate_token_budget(IntentType.CODE_REVIEW, ["github"], 8_000)
        assert result == {"github": 8_000}

    def test_single_source_unlisted_receives_total_budget(self) -> None:
        result = allocate_token_budget(IntentType.CODE_REVIEW, ["confluence"], 8_000)
        assert result == {"confluence": 8_000}

    def test_single_source_minimum_floor_respected(self) -> None:
        result = allocate_token_budget(IntentType.GENERAL, ["github"], 100)
        assert result["github"] >= 200

    def test_single_source_default_budget(self) -> None:
        result = allocate_token_budget(IntentType.DEBUGGING, ["github"])
        assert "github" in result
        assert result["github"] >= 200


class TestAllocateTokenBudgetMultiSource:
    def test_incident_three_sources_sum_gte_total_budget(self) -> None:
        result = allocate_token_budget(
            IntentType.INCIDENT, ["grafana", "jira", "pagerduty"], 8_000
        )
        assert len(result) == 3
        assert sum(result.values()) >= 8_000

    def test_incident_grafana_largest_allocation(self) -> None:
        result = allocate_token_budget(
            IntentType.INCIDENT, ["grafana", "jira", "pagerduty"], 8_000
        )
        assert result["grafana"] > result["jira"]
        assert result["grafana"] > result["pagerduty"]

    def test_incident_jira_larger_than_pagerduty(self) -> None:
        result = allocate_token_budget(
            IntentType.INCIDENT, ["grafana", "jira", "pagerduty"], 8_000
        )
        assert result["jira"] > result["pagerduty"]

    def test_all_sources_receive_minimum_200_tokens(self) -> None:
        result = allocate_token_budget(
            IntentType.GENERAL, ["confluence", "github", "stackoverflow"], 600
        )
        for source, quota in result.items():
            assert quota >= 200, f"{source} received {quota} < 200"

    def test_all_keys_present_in_result(self) -> None:
        sources = ["confluence", "github", "stackoverflow"]
        result = allocate_token_budget(IntentType.GENERAL, sources, 8_000)
        assert set(result.keys()) == set(sources)

    def test_proportional_split_code_gen(self) -> None:
        # github weight=4, confluence weight=2 → github should get ~2x confluence
        result = allocate_token_budget(
            IntentType.CODE_GEN, ["github", "confluence"], 6_000
        )
        assert result["github"] > result["confluence"]

    def test_debugging_github_stackoverflow_equal_weight(self) -> None:
        # Both have weight 3 → allocations should be equal
        result = allocate_token_budget(
            IntentType.DEBUGGING, ["github", "stackoverflow"], 8_000
        )
        # Equal weights; last source absorbs rounding — allow small delta
        assert abs(result["github"] - result["stackoverflow"]) <= 1

    def test_unlisted_source_gets_weight_one(self) -> None:
        # "unknown_source" not in INCIDENT weights → weight 1 vs grafana weight 4
        result = allocate_token_budget(
            IntentType.INCIDENT, ["grafana", "unknown_source"], 8_000
        )
        assert result["grafana"] > result["unknown_source"]

    def test_unknown_intent_falls_back_to_equal_weights(self) -> None:
        # IntentType values are exhaustive, but passing a valid enum value not in
        # SOURCE_WEIGHT_TABLE would default to equal weights (weight_row = {}).
        # Use GENERAL (which IS listed) with two equal-weight unlisted sources.
        result = allocate_token_budget(
            IntentType.CODE_REVIEW, ["source_a", "source_b"], 8_000
        )
        # Both unlisted → weight 1 each → roughly equal
        assert abs(result["source_a"] - result["source_b"]) <= 1


class TestAllocateTokenBudgetFloorGuarantee:
    def test_floor_guarantee_with_large_source_list(self) -> None:
        sources = [f"src_{i}" for i in range(20)]
        result = allocate_token_budget(IntentType.GENERAL, sources, 8_000)
        for source, quota in result.items():
            assert quota >= 200, f"{source} received {quota} < 200"

    def test_floor_may_cause_total_to_exceed_budget(self) -> None:
        # When many low-weight sources force floor, total may exceed total_budget.
        # callers must tolerate delta < len(source_list) * MIN_ALLOC.
        sources = [f"src_{i}" for i in range(50)]
        total_budget = 1_000
        result = allocate_token_budget(IntentType.GENERAL, sources, total_budget)
        for quota in result.values():
            assert quota >= 200


class TestSourceWeightTableCompleteness:
    def test_all_intent_types_covered(self) -> None:
        for intent in IntentType:
            assert intent in SOURCE_WEIGHT_TABLE, f"{intent} missing from SOURCE_WEIGHT_TABLE"

    def test_default_total_budget_value(self) -> None:
        assert DEFAULT_TOTAL_BUDGET == 8_000
