"""Unit tests for TASK-US019-04 — routing_node() LangGraph node.

Coverage:
- Successful model selection: ``ModelRouter.select()`` returns a ``ModelScore``
- Fallback on ``None``: uses ``RoutingSettings.fallback_model_id``
- OTel span attributes: all 5 attributes verified via InMemorySpanExporter
- Langfuse event emission when ``langfuse`` is not ``None``
- ``langfuse=None`` guard: no exception, no Langfuse calls executed
- CI latency benchmark: routing completes in < 50 ms with mocked Redis
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.agents.nodes.routing_node import routing_node
from src.agents.schemas.execution_plan import ExecutionPlan, RankingStrategy
from src.agents.schemas.intent import IntentType
from src.agents.state import AgentState, ExecutionStatus
from src.model_router.schemas.model_score import ModelScore
from src.model_router.schemas.routing_weights import RoutingWeights

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides: Any) -> AgentState:
    base: AgentState = {
        "request_id": "req-test",
        "user_id": "user-1",
        "username": "tester",
        "roles": ["user"],
        "tool_name": "search",
        "prompt": "Explain the deployment pipeline",
        "timestamp": "2026-07-18T00:00:00Z",
        "status": ExecutionStatus.RUNNING,
        "current_node": "routing_agent",
        "error": None,
        "intent_type": IntentType.GENERAL,
        "intent_confidence": 0.9,
        "intent_source_list": None,
        "execution_plan": None,
        "requires_clarification": None,
        "clarification_question": None,
        "clarification_round": 0,
        "raw_context": None,
        "ranked_context": None,
        "degraded_sources": None,
        "compressed_context": None,
        "removed_chunks": None,
        "tokens_before_compression": None,
        "tokens_after_compression": None,
        "governance_decisions": None,
        "redacted_chunks": None,
        "selected_model": None,
        "model_routing_score": None,
        "final_response": None,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _make_plan() -> ExecutionPlan:
    return ExecutionPlan(
        sources=["github"],
        token_budget_total=8_000,
        token_budget_per_source={"github": 8_000},
        ranking_strategy=RankingStrategy.HYBRID,
        cache_eligible=False,
    )


def _make_model_score(
    model_id: str = "gpt-4o",
    composite_score: float = 0.85,
    quality_score: float = 0.9,
    normalised_cost: float = 0.5,
    normalised_latency: float = 0.8,
) -> ModelScore:
    return ModelScore(
        model_id=model_id,
        quality_score=quality_score,
        normalised_cost=normalised_cost,
        normalised_latency=normalised_latency,
        composite_score=composite_score,
    )


def _make_caches(selection: ModelScore | None) -> tuple[MagicMock, MagicMock]:
    """Return (model_list_cache, scored_cache) mocks with router.select() returning selection."""
    model_list_cache = MagicMock()
    scored_cache = MagicMock()
    return model_list_cache, scored_cache


# ---------------------------------------------------------------------------
# TestRoutingNodeSuccessfulSelection
# ---------------------------------------------------------------------------


class TestRoutingNodeSuccessfulSelection:
    @pytest.mark.asyncio
    async def test_writes_selected_model_id_to_state(self) -> None:
        score = _make_model_score("gpt-4o", 0.85)
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state(execution_plan=_make_plan())

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            result = await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        assert result["selected_model_id"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_writes_routing_score_to_state(self) -> None:
        score = _make_model_score("gpt-4o", 0.85)
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state(execution_plan=_make_plan())

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            result = await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        assert result["routing_score"] == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_preserves_existing_state_fields(self) -> None:
        score = _make_model_score("gpt-4o")
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state(execution_plan=_make_plan())

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            result = await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        assert result["request_id"] == "req-test"
        assert result["user_id"] == "user-1"
        assert result["status"] == ExecutionStatus.RUNNING


# ---------------------------------------------------------------------------
# TestRoutingNodeFallback
# ---------------------------------------------------------------------------


class TestRoutingNodeFallback:
    @pytest.mark.asyncio
    async def test_uses_fallback_model_when_select_returns_none(self) -> None:
        model_list_cache, scored_cache = _make_caches(None)
        state = _make_state()

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = None
            result = await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        assert result["selected_model_id"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_routing_score_zero_on_fallback(self) -> None:
        model_list_cache, scored_cache = _make_caches(None)
        state = _make_state()

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = None
            result = await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        assert result["routing_score"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_no_exception_on_fallback(self) -> None:
        model_list_cache, scored_cache = _make_caches(None)
        state = _make_state()

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = None
            result = await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        assert "selected_model_id" in result


# ---------------------------------------------------------------------------
# TestRoutingNodeIntentExtraction
# ---------------------------------------------------------------------------


class TestRoutingNodeIntentExtraction:
    @pytest.mark.asyncio
    async def test_uses_intent_from_state(self) -> None:
        score = _make_model_score()
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state(intent_type=IntentType.CODE_GEN)

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        _, kwargs = mock_select.await_args
        assert kwargs["intent_type"] == "code-gen"
        assert kwargs["cache_key"] == "code-gen:q0.625:c0.235:l0.140"
        assert kwargs["weights"] == RoutingWeights(
            quality_weight=0.625,
            cost_weight=0.235,
            latency_weight=0.14,
        )

    @pytest.mark.asyncio
    async def test_defaults_to_general_when_no_execution_plan(self) -> None:
        score = _make_model_score()
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state(execution_plan=None)

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        _, kwargs = mock_select.await_args
        assert kwargs["intent_type"] == "general"
        assert kwargs["weights"] == RoutingWeights(
            quality_weight=0.4,
            cost_weight=0.4,
            latency_weight=0.2,
        )

    @pytest.mark.asyncio
    async def test_defaults_to_general_when_no_intent_type_in_plan(self) -> None:
        score = _make_model_score()
        model_list_cache, scored_cache = _make_caches(score)
        # ExecutionPlan without intent_type in the dict
        state = _make_state()
        state["execution_plan"] = {}  # type: ignore[typeddict-item]

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        _, kwargs = mock_select.await_args
        assert kwargs["intent_type"] == "general"

    @pytest.mark.asyncio
    async def test_blends_toward_general_weights_at_low_confidence(self) -> None:
        score = _make_model_score()
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state(intent_type=IntentType.CODE_GEN, intent_confidence=0.2)

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        _, kwargs = mock_select.await_args
        assert kwargs["weights"] == RoutingWeights(
            quality_weight=0.46,
            cost_weight=0.36,
            latency_weight=0.18,
        )


# ---------------------------------------------------------------------------
# TestRoutingNodeOtelSpan
# ---------------------------------------------------------------------------


class TestRoutingNodeOtelSpan:
    @pytest.fixture(autouse=True)
    def _setup_otel(self):
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        with patch("src.agents.nodes.routing_node._tracer", provider.get_tracer(__name__)):
            yield

    @pytest.mark.asyncio
    async def test_span_name_is_model_router_select(self) -> None:
        score = _make_model_score("gpt-4o", 0.8)
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state(intent_type=IntentType.DEBUGGING)

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        spans = self.exporter.get_finished_spans()
        assert any(s.name == "model_router.select" for s in spans)

    @pytest.mark.asyncio
    async def test_span_has_all_5_attributes(self) -> None:
        score = _make_model_score("gpt-4o", 0.8)
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state(intent_type=IntentType.DEBUGGING)

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        spans = self.exporter.get_finished_spans()
        routing_span = next(s for s in spans if s.name == "model_router.select")
        attrs = dict(routing_span.attributes or {})

        assert attrs["routing.model_id"] == "gpt-4o"
        assert attrs["routing.score"] == pytest.approx(0.8)
        assert attrs["routing.intent"] == "debugging"
        assert "routing.latency_ms" in attrs
        assert attrs["routing.fallback"] is False

    @pytest.mark.asyncio
    async def test_span_fallback_true_when_select_returns_none(self) -> None:
        model_list_cache, scored_cache = _make_caches(None)
        state = _make_state()

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = None
            await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        spans = self.exporter.get_finished_spans()
        routing_span = next(s for s in spans if s.name == "model_router.select")
        attrs = dict(routing_span.attributes or {})

        assert attrs["routing.fallback"] is True
        assert attrs["routing.model_id"] == "gpt-4o-mini"
        assert attrs["routing.score"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestRoutingNodeLangfuse
# ---------------------------------------------------------------------------


class TestRoutingNodeLangfuse:
    @pytest.mark.asyncio
    async def test_langfuse_event_emitted_when_provided(self) -> None:
        score = _make_model_score("gpt-4o", 0.75)
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state(intent_type=IntentType.GENERAL)
        mock_langfuse = MagicMock()

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            await routing_node(state, model_list_cache, scored_cache, langfuse=mock_langfuse)

        mock_langfuse.event.assert_called_once()
        call_kwargs = mock_langfuse.event.call_args.kwargs
        assert call_kwargs["name"] == "model_routing_decision"
        assert call_kwargs["output"]["model_id"] == "gpt-4o"
        assert call_kwargs["output"]["score"] == pytest.approx(0.75)
        assert call_kwargs["input"]["intent_type"] == "general"

    @pytest.mark.asyncio
    async def test_langfuse_metadata_includes_routing_reason(self) -> None:
        score = _make_model_score("gpt-4o", 0.75)
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state(intent_type=IntentType.GENERAL)
        mock_langfuse = MagicMock()

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            await routing_node(state, model_list_cache, scored_cache, langfuse=mock_langfuse)

        call_kwargs = mock_langfuse.event.call_args.kwargs
        assert "routing_reason" in call_kwargs["metadata"]
        assert "latency_ms" in call_kwargs["metadata"]
        assert call_kwargs["metadata"]["used_fallback"] is False

    @pytest.mark.asyncio
    async def test_langfuse_not_called_when_none(self) -> None:
        score = _make_model_score()
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state()

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            # Must not raise even though langfuse is None
            result = await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        assert result["selected_model_id"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_no_exception_when_langfuse_none_and_fallback(self) -> None:
        model_list_cache, scored_cache = _make_caches(None)
        state = _make_state()

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = None
            # Must not raise
            result = await routing_node(state, model_list_cache, scored_cache, langfuse=None)

        assert result["routing_score"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_langfuse_fallback_event_metadata(self) -> None:
        model_list_cache, scored_cache = _make_caches(None)
        state = _make_state()
        mock_langfuse = MagicMock()

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = None
            await routing_node(state, model_list_cache, scored_cache, langfuse=mock_langfuse)

        call_kwargs = mock_langfuse.event.call_args.kwargs
        assert call_kwargs["metadata"]["used_fallback"] is True
        assert call_kwargs["output"]["model_id"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# TestRoutingNodeLatencyBenchmark
# ---------------------------------------------------------------------------


class TestRoutingNodeLatencyBenchmark:
    @pytest.mark.asyncio
    async def test_routing_latency_under_50ms_with_mocked_redis(self) -> None:
        """CI benchmark: routing completes in < 50 ms when Redis is mocked."""
        score = _make_model_score("gpt-4o", 0.9)
        model_list_cache, scored_cache = _make_caches(score)
        state = _make_state(intent_type=IntentType.GENERAL)

        with patch(
            "src.agents.nodes.routing_node.ModelRouter.select", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = score
            t0 = time.perf_counter()
            await routing_node(state, model_list_cache, scored_cache, langfuse=None)
            elapsed_ms = (time.perf_counter() - t0) * 1000

        assert elapsed_ms < 50.0, f"Routing latency {elapsed_ms:.1f} ms exceeds 50 ms SLA"
