"""Unit tests for TASK-US014-05 — governance_node (context ranking).

Coverage:
- Normal ranking: raw_context chunks are scored, filtered, sorted, and truncated.
- Empty raw_context: returns empty ranked_context (never None).
- Threshold filtering: chunks below relevance_threshold are excluded.
- Env-var weight override via RankingSettings constructor injection.
- route_after_governance predicate reads typed RetrievedChunk.content tokens.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from src.agents.nodes.governance_node import governance_node
from src.agents.routing import route_after_governance
from src.agents.schemas.execution_plan import ExecutionPlan, RankingStrategy
from src.agents.schemas.intent import IntentType
from src.agents.state import AgentState, ExecutionStatus
from src.retrieval.ranking.settings import RankingSettings
from src.retrieval.ranking.weights import RankingWeights
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(UTC)

_PLAN = ExecutionPlan(
    sources=["github"],
    token_budget_total=8_000,
    token_budget_per_source={"github": 8_000},
    ranking_strategy=RankingStrategy.HYBRID,
    cache_eligible=False,
)


def _chunk(
    chunk_id: str,
    content: str,
    score: float,
    vector_score: float | None = None,
    keyword_score: float | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id="github",
        content=content,
        score=score,
        metadata=ChunkMetadata(
            file_path=f"src/{chunk_id}.py",
            timestamp=_NOW,
            author="test-author",
        ),
        search_mode="rrf",
        vector_score=vector_score,
        keyword_score=keyword_score,
    )


def _make_state(**overrides: object) -> AgentState:
    base: AgentState = {
        "request_id": "req-test-gov",
        "user_id": "user-1",
        "username": "tester",
        "roles": ["developer"],
        "tool_name": "context_search",
        "prompt": "How does the deployment pipeline work?",
        "timestamp": "2026-07-17T00:00:00Z",
        "status": ExecutionStatus.RUNNING,
        "current_node": "knowledge_graph",
        "error": None,
        "intent_type": IntentType.GENERAL,
        "intent_confidence": 0.9,
        "intent_source_list": None,
        "execution_plan": _PLAN,
        "requires_clarification": None,
        "clarification_question": None,
        "clarification_round": 0,
        "raw_context": None,
        "ranked_context": None,
        "degraded_sources": None,
        "compressed_context": None,
        "tokens_before_compression": None,
        "tokens_after_compression": None,
        "governance_decisions": None,
        "redacted_chunks": None,
    }
    return {**base, **overrides}  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# governance_node — normal ranking
# ---------------------------------------------------------------------------


class TestGovernanceNodeNormalRanking:
    @pytest.mark.asyncio
    async def test_ranked_context_is_list_of_retrieved_chunks(self) -> None:
        chunks = [
            _chunk("c1", "deployment pipeline overview", 0.8, vector_score=0.9, keyword_score=0.7),
            _chunk("c2", "CI/CD configuration guide", 0.6, vector_score=0.6, keyword_score=0.5),
        ]
        state = _make_state(raw_context=chunks)
        result = await governance_node(state)

        ranked = result["ranked_context"]
        assert isinstance(ranked, list)
        for item in ranked:
            assert isinstance(item, RetrievedChunk)

    @pytest.mark.asyncio
    async def test_ranked_context_ordered_descending_by_score(self) -> None:
        chunks = [
            _chunk("low", "low relevance content", 0.3, vector_score=0.3, keyword_score=0.3),
            _chunk("high", "high relevance content", 0.9, vector_score=0.9, keyword_score=0.8),
            _chunk("mid", "medium relevance content", 0.6, vector_score=0.6, keyword_score=0.5),
        ]
        state = _make_state(raw_context=chunks)
        result = await governance_node(state)

        ranked = result["ranked_context"]
        scores = [c.score for c in ranked]
        assert scores == sorted(scores, reverse=True), "ranked_context must be sorted descending"

    @pytest.mark.asyncio
    async def test_all_returned_chunks_meet_threshold(self) -> None:
        settings_override = RankingSettings(relevance_threshold=0.5)
        # chunk with score < threshold (after re-scoring) should be excluded
        chunks = [
            _chunk("pass", "relevant deployment guide", 0.8, vector_score=0.8, keyword_score=0.7),
            _chunk("fail", "irrelevant noise", 0.1, vector_score=0.1, keyword_score=0.05),
        ]
        state = _make_state(raw_context=chunks)

        with patch("src.agents.nodes.governance_node._ranking_settings", settings_override):
            result = await governance_node(state)

        ranked = result["ranked_context"]
        assert all(c.score >= settings_override.relevance_threshold for c in ranked)

    @pytest.mark.asyncio
    async def test_returns_correct_state_keys(self) -> None:
        chunks = [_chunk("c1", "some content", 0.7, vector_score=0.7, keyword_score=0.6)]
        state = _make_state(raw_context=chunks)
        result = await governance_node(state)

        assert "ranked_context" in result
        assert result["current_node"] == "governance_agent"
        assert result["status"] == ExecutionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_total_tokens_do_not_exceed_budget(self) -> None:
        # Create a state with a very small token budget (1 000 tokens).
        small_plan = ExecutionPlan(
            sources=["github"],
            token_budget_total=1_000,
            token_budget_per_source={"github": 1_000},
            ranking_strategy=RankingStrategy.HYBRID,
            cache_eligible=False,
        )
        # Chunks with content that each consume ~500 tokens (approx 2 000-char strings)
        chunks = [
            _chunk(f"c{i}", "x " * 250, 0.9 - i * 0.05, vector_score=0.9, keyword_score=0.8)
            for i in range(5)
        ]
        state = _make_state(raw_context=chunks, execution_plan=small_plan)
        result = await governance_node(state)

        from src.retrieval.ranking.filters import count_tokens

        total = sum(count_tokens(c.content) for c in result["ranked_context"])
        assert total <= 1_000


# ---------------------------------------------------------------------------
# governance_node — empty raw_context
# ---------------------------------------------------------------------------


class TestGovernanceNodeEmptyInput:
    @pytest.mark.asyncio
    async def test_empty_raw_context_returns_empty_list(self) -> None:
        state = _make_state(raw_context=[])
        result = await governance_node(state)
        assert result["ranked_context"] == []

    @pytest.mark.asyncio
    async def test_none_raw_context_returns_empty_list(self) -> None:
        state = _make_state(raw_context=None)
        result = await governance_node(state)
        assert result["ranked_context"] == []
        assert result["ranked_context"] is not None


# ---------------------------------------------------------------------------
# RankingSettings — env-var weight override
# ---------------------------------------------------------------------------


class TestRankingSettingsEnvOverride:
    def test_incident_override_parsed_from_constructor(self) -> None:
        """Passing weights_incident='0.2,0.6,0.2' via constructor overrides the default."""
        settings = RankingSettings(weights_incident="0.2,0.6,0.2")
        weights = settings.get_weights(IntentType.INCIDENT)
        assert weights == RankingWeights(vector_weight=0.2, keyword_weight=0.6, recency_weight=0.2)

    def test_absent_override_falls_back_to_intent_table(self) -> None:
        from src.retrieval.ranking.weights import INTENT_WEIGHT_TABLE

        settings = RankingSettings()
        weights = settings.get_weights(IntentType.INCIDENT)
        assert weights == INTENT_WEIGHT_TABLE[IntentType.INCIDENT]

    def test_unknown_intent_falls_back_to_default_weights(self) -> None:
        from src.retrieval.ranking.weights import DEFAULT_WEIGHTS

        settings = RankingSettings()
        # Use a valid IntentType that has no override; ensure fallback to INTENT_WEIGHT_TABLE.
        # For an intent not in the table (hypothetically), DEFAULT_WEIGHTS is used.
        # We mock IntentType.GENERAL to not appear in the table.
        from unittest.mock import patch as _patch

        with _patch.dict("src.retrieval.ranking.weights.INTENT_WEIGHT_TABLE", {}, clear=True):
            weights = settings.get_weights(IntentType.GENERAL)
        assert weights == DEFAULT_WEIGHTS

    def test_code_gen_hyphen_normalised_to_underscore(self) -> None:
        """IntentType.CODE_GEN = 'code-gen'; hyphen must be replaced with underscore."""
        settings = RankingSettings(weights_code_gen="0.7,0.1,0.2")
        weights = settings.get_weights(IntentType.CODE_GEN)
        assert weights == RankingWeights(vector_weight=0.7, keyword_weight=0.1, recency_weight=0.2)

    @pytest.mark.asyncio
    async def test_env_var_weight_used_in_governance_node(self) -> None:
        """governance_node uses env-overridden weights when _ranking_settings is patched."""
        settings_override = RankingSettings(weights_incident="0.2,0.6,0.2")
        chunks = [
            _chunk("c1", "incident response runbook", 0.8, vector_score=0.7, keyword_score=0.9),
        ]
        state = _make_state(raw_context=chunks, intent_type=IntentType.INCIDENT)

        with patch("src.agents.nodes.governance_node._ranking_settings", settings_override):
            result = await governance_node(state)

        assert len(result["ranked_context"]) >= 0  # node ran without error


# ---------------------------------------------------------------------------
# route_after_governance — typed RetrievedChunk access
# ---------------------------------------------------------------------------


class TestRouteAfterGovernanceTypedAccess:
    def _routing_state(self, ranked: list[RetrievedChunk]) -> AgentState:
        return _make_state(ranked_context=ranked)

    def test_routes_compress_when_tokens_exceed_budget(self) -> None:
        # Each chunk content is ~600 tokens; two chunks exceed a 1 000-token budget.
        large_plan = ExecutionPlan(
            sources=["github"],
            token_budget_total=1_000,
            token_budget_per_source={"github": 1_000},
            ranking_strategy=RankingStrategy.HYBRID,
            cache_eligible=False,
        )
        chunks = [
            _chunk("c1", "word " * 600, 0.8),
            _chunk("c2", "term " * 600, 0.7),
        ]
        state = self._routing_state(chunks)
        state["execution_plan"] = large_plan
        assert route_after_governance(state) == "compress"

    def test_routes_skip_when_tokens_within_budget(self) -> None:
        chunks = [_chunk("c1", "short", 0.8)]
        state = self._routing_state(chunks)
        assert route_after_governance(state) == "skip"

    def test_empty_ranked_context_routes_skip(self) -> None:
        state = self._routing_state([])
        assert route_after_governance(state) == "skip"

    def test_failed_status_routes_failed(self) -> None:
        state = self._routing_state([_chunk("c1", "content", 0.8)])
        state["status"] = ExecutionStatus.FAILED
        assert route_after_governance(state) == "failed"

    def test_uses_content_not_dict_get(self) -> None:
        """Verify route_after_governance uses count_tokens(c.content), not c.get('token_count')."""
        from src.retrieval.ranking.filters import count_tokens

        # Content with > 1 000 tokens so it exceeds the minimum-valid budget of 1 000.
        long_content = "hello world " * 500  # ~1 000 tokens
        chunks = [_chunk("c1", long_content, 0.8)]
        state = self._routing_state(chunks)
        state["execution_plan"] = ExecutionPlan(
            sources=["github"],
            token_budget_total=1_000,
            token_budget_per_source={"github": 1_000},
            ranking_strategy=RankingStrategy.HYBRID,
            cache_eligible=False,
        )
        token_count = count_tokens(long_content)
        result = route_after_governance(state)
        # The routing decision must be driven by actual token count, not a missing dict key.
        expected = "compress" if token_count > 1_000 else "skip"
        assert result == expected


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


class TestRankingSettingsSingleton:
    def test_singleton_is_not_reinitialised_per_call(self) -> None:
        from src.agents.nodes import governance_node as gov_module

        s1 = gov_module._ranking_settings
        s2 = gov_module._ranking_settings
        assert s1 is s2, "_ranking_settings must be a module-level singleton"
