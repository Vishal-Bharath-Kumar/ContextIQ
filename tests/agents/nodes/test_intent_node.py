"""Unit tests for TASK-US009-01 / TASK-US009-05 — intent_node() and IntentResult schema.

All LLM calls are mocked — no live API calls in CI.

Coverage targets:
- All 8 IntentType variants via parametrised tests
- IntentResult validation (confidence bounds)
- intent_node() output shape
- Performance guard: mocked chain latency ≤ 250 ms
- OTel span attributes: all four attributes for high- and low-confidence outcomes
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from src.agents.nodes.intent import SYSTEM_PROMPT, intent_node
from src.agents.schemas.intent import IntentResult, IntentType
from src.agents.state import AgentState, ExecutionStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(prompt: str = "test prompt") -> AgentState:
    return {
        "request_id": "req-test",
        "user_id": "user-1",
        "username": "tester",
        "roles": ["user"],
        "tool_name": "search",
        "prompt": prompt,
        "timestamp": "2026-01-01T00:00:00Z",
        "status": ExecutionStatus.RUNNING,
        "current_node": "intent_agent",
        "error": None,
        "intent_type": None,
        "intent_confidence": None,
        "execution_plan": None,
        "raw_context": None,
        "ranked_context": None,
        "degraded_sources": None,
        "compressed_context": None,
        "tokens_before_compression": None,
        "tokens_after_compression": None,
        "governance_decisions": None,
        "redacted_chunks": None,
        "selected_model": None,
        "model_routing_score": None,
        "final_response": None,
    }


def _llm_response(intent_type: str, confidence: float = 0.95) -> dict[str, Any]:
    return {
        "intent_type": intent_type,
        "confidence": confidence,
        "reasoning": f"The prompt is about {intent_type}.",
    }


def _mock_chain(intent_type: str, confidence: float = 0.95) -> MagicMock:
    """Return a mock chain whose ``ainvoke`` returns a fixed LLM response."""
    chain = MagicMock()
    chain.ainvoke = AsyncMock(return_value=_llm_response(intent_type, confidence))
    return chain


# ---------------------------------------------------------------------------
# IntentResult schema tests
# ---------------------------------------------------------------------------


class TestIntentResult:
    def test_valid_model(self) -> None:
        result = IntentResult(
            intent_type=IntentType.DEBUGGING,
            confidence=0.9,
            reasoning="The prompt describes a bug.",
        )
        assert result.intent_type == IntentType.DEBUGGING
        assert result.confidence == 0.9

    def test_confidence_lower_bound_valid(self) -> None:
        result = IntentResult(
            intent_type=IntentType.GENERAL, confidence=0.0, reasoning="ok"
        )
        assert result.confidence == 0.0

    def test_confidence_upper_bound_valid(self) -> None:
        result = IntentResult(
            intent_type=IntentType.GENERAL, confidence=1.0, reasoning="ok"
        )
        assert result.confidence == 1.0

    def test_confidence_above_1_raises(self) -> None:
        with pytest.raises(ValidationError):
            IntentResult(intent_type=IntentType.GENERAL, confidence=1.01, reasoning="x")

    def test_confidence_below_0_raises(self) -> None:
        with pytest.raises(ValidationError):
            IntentResult(intent_type=IntentType.GENERAL, confidence=-0.01, reasoning="x")

    def test_invalid_intent_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            IntentResult(intent_type="unknown-type", confidence=0.8, reasoning="x")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# IntentType enum coverage
# ---------------------------------------------------------------------------


class TestIntentType:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("debugging", IntentType.DEBUGGING),
            ("code-gen", IntentType.CODE_GEN),
            ("architecture", IntentType.ARCHITECTURE),
            ("docs", IntentType.DOCS),
            ("incident", IntentType.INCIDENT),
            ("metrics", IntentType.METRICS),
            ("code-review", IntentType.CODE_REVIEW),
            ("general", IntentType.GENERAL),
        ],
    )
    def test_all_variants_parseable(self, value: str, expected: IntentType) -> None:
        assert IntentType(value) == expected

    def test_eight_variants_total(self) -> None:
        assert len(IntentType) == 8


# ---------------------------------------------------------------------------
# intent_node() output shape and correctness
# ---------------------------------------------------------------------------


class TestIntentNodeOutput:
    @pytest.mark.asyncio
    async def test_classifies_debugging_prompt(self) -> None:
        with patch(
            "src.agents.nodes.intent._get_chain",
            return_value=_mock_chain("debugging", 0.95),
        ):
            result = await intent_node(_make_state("Why does my function return None?"))

        assert result["intent_type"] == IntentType.DEBUGGING
        assert result["intent_confidence"] == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_classifies_docs_prompt(self) -> None:
        with patch(
            "src.agents.nodes.intent._get_chain",
            return_value=_mock_chain("docs", 0.88),
        ):
            result = await intent_node(
                _make_state("How do I set up Redis for caching?")
            )

        assert result["intent_type"] == IntentType.DOCS
        assert result["intent_confidence"] == pytest.approx(0.88)

    @pytest.mark.asyncio
    async def test_return_dict_has_intent_keys(self) -> None:
        with patch(
            "src.agents.nodes.intent._get_chain",
            return_value=_mock_chain("general", 0.7),
        ):
            result = await intent_node(_make_state("hello"))

        assert "intent_type" in result
        assert "intent_confidence" in result
        assert result["intent_type"] is not None
        assert result["intent_confidence"] is not None

    @pytest.mark.asyncio
    async def test_current_node_set_to_intent_agent(self) -> None:
        with patch(
            "src.agents.nodes.intent._get_chain",
            return_value=_mock_chain("general", 0.7),
        ):
            result = await intent_node(_make_state("hello"))

        assert result["current_node"] == "intent_agent"

    @pytest.mark.asyncio
    async def test_status_set_to_running(self) -> None:
        with patch(
            "src.agents.nodes.intent._get_chain",
            return_value=_mock_chain("general", 0.7),
        ):
            result = await intent_node(_make_state("hello"))

        assert result["status"] == ExecutionStatus.RUNNING


# ---------------------------------------------------------------------------
# Parametrised tests: all 8 intent types reachable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent_value",
    [
        "debugging",
        "code-gen",
        "architecture",
        "docs",
        "incident",
        "metrics",
        "code-review",
        "general",
    ],
)
async def test_all_intent_types_reachable(intent_value: str) -> None:
    """Verify that every canonical intent type can be returned by intent_node()."""
    with patch(
        "src.agents.nodes.intent._get_chain",
        return_value=_mock_chain(intent_value, 0.9),
    ):
        result = await intent_node(_make_state("some prompt"))

    assert result["intent_type"] == IntentType(intent_value)


# ---------------------------------------------------------------------------
# Performance guard: mocked latency ≤ 250 ms
# ---------------------------------------------------------------------------


class TestIntentNodePerformance:
    @pytest.mark.asyncio
    async def test_classification_completes_within_250ms(self) -> None:
        """Mocked chain must resolve in well under 250 ms (CI latency budget)."""
        with patch(
            "src.agents.nodes.intent._get_chain",
            return_value=_mock_chain("metrics", 0.92),
        ):
            start = time.monotonic()
            await intent_node(_make_state("x" * 2000))
            elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 250, f"Took {elapsed_ms:.1f} ms — exceeds 250 ms budget"


# ---------------------------------------------------------------------------
# System prompt sanity check
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_system_prompt_contains_all_intent_types(self) -> None:
        for intent in IntentType:
            assert intent.value in SYSTEM_PROMPT, (
                f"SYSTEM_PROMPT missing intent type: {intent.value}"
            )

    def test_system_prompt_requests_json_output(self) -> None:
        assert "JSON" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# OTel span attribute tests (TASK-US009-05)
# ---------------------------------------------------------------------------


def _make_in_memory_tracer() -> tuple[InMemorySpanExporter, object]:
    """Return (exporter, tracer) backed by an in-memory span exporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test.intent")
    return exporter, tracer


class TestIntentNodeOtelSpans:
    """Verify that intent_node() sets all four OTel span attributes."""

    @pytest.mark.asyncio
    async def test_span_attributes_high_confidence(self) -> None:
        """All four span attributes are set correctly for a high-confidence result."""
        exporter, tracer = _make_in_memory_tracer()
        with patch("src.agents.nodes.intent._tracer", tracer):
            with patch(
                "src.agents.nodes.intent._get_chain",
                return_value=_mock_chain("debugging", 0.87),
            ):
                result = await intent_node(_make_state("Why does this crash?"))

        spans = exporter.get_finished_spans()
        assert len(spans) == 1, "Expected exactly one span"
        attrs = spans[0].attributes

        assert attrs["intent.type"] == "debugging"
        assert attrs["intent.confidence"] == pytest.approx(0.87)
        assert attrs["intent.latency_ms"] >= 0.0
        assert attrs["intent.low_confidence"] is False

        # Return value must not be altered by instrumentation
        assert result["intent_type"] == "debugging"
        assert result["intent_confidence"] == pytest.approx(0.87)

    @pytest.mark.asyncio
    async def test_span_attributes_low_confidence(self) -> None:
        """``intent.low_confidence`` is True when confidence < 0.6."""
        exporter, tracer = _make_in_memory_tracer()
        with patch("src.agents.nodes.intent._tracer", tracer):
            with patch(
                "src.agents.nodes.intent._get_chain",
                return_value=_mock_chain("general", 0.45),
            ):
                result = await intent_node(_make_state("something vague"))

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        attrs = spans[0].attributes

        assert attrs["intent.type"] == "general"
        assert attrs["intent.confidence"] == pytest.approx(0.45)
        assert attrs["intent.latency_ms"] >= 0.0
        assert attrs["intent.low_confidence"] is True

        assert result["intent_type"] == "general"
        assert result["intent_confidence"] == pytest.approx(0.45)

    @pytest.mark.asyncio
    async def test_span_name_is_intent_agent_classify(self) -> None:
        """Span name matches the defined contract ``intent_agent.classify``."""
        exporter, tracer = _make_in_memory_tracer()
        with patch("src.agents.nodes.intent._tracer", tracer):
            with patch(
                "src.agents.nodes.intent._get_chain",
                return_value=_mock_chain("docs", 0.75),
            ):
                await intent_node(_make_state("how do I document this?"))

        spans = exporter.get_finished_spans()
        assert spans[0].name == "intent_agent.classify"

    @pytest.mark.asyncio
    async def test_span_latency_ms_is_non_negative(self) -> None:
        """``intent.latency_ms`` is a non-negative float."""
        exporter, tracer = _make_in_memory_tracer()
        with patch("src.agents.nodes.intent._tracer", tracer):
            with patch(
                "src.agents.nodes.intent._get_chain",
                return_value=_mock_chain("code-gen", 0.9),
            ):
                await intent_node(_make_state("write a sort function"))

        attrs = exporter.get_finished_spans()[0].attributes
        assert isinstance(attrs["intent.latency_ms"], float)
        assert attrs["intent.latency_ms"] >= 0.0

    @pytest.mark.asyncio
    async def test_low_confidence_boundary_at_threshold(self) -> None:
        """Confidence exactly at 0.6 is NOT low-confidence (strict less-than)."""
        exporter, tracer = _make_in_memory_tracer()
        with patch("src.agents.nodes.intent._tracer", tracer):
            with patch(
                "src.agents.nodes.intent._get_chain",
                return_value=_mock_chain("architecture", 0.6),
            ):
                await intent_node(_make_state("design a microservice"))

        attrs = exporter.get_finished_spans()[0].attributes
        assert attrs["intent.low_confidence"] is False

