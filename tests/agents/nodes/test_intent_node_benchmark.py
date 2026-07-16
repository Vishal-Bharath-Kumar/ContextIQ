"""CI latency benchmark for intent_node() — TASK-US009-05.

Asserts that intent_node() (with a mocked LLM) completes within 500 ms for a
2 000-token prompt.  The benchmark is gated by ``pytest-benchmark``; the CI
pipeline fails if the p95 exceeds the 500 ms budget.

Run in isolation:
    pytest tests/agents/nodes/test_intent_node_benchmark.py -v --benchmark-only
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

# ≈ 2 000 tokens: "def foo():\n    " + "pass\n    " repeated 400 times
PROMPT_2000_TOKENS = "def foo():\n    " + "pass\n    " * 400

_MOCK_RESULT = {"intent_type": "debugging", "confidence": 0.92, "reasoning": "test"}


@pytest.mark.benchmark(max_time=0.5)
def test_intent_node_latency(benchmark: pytest.fixture) -> None:
    """intent_node() with a mocked chain must complete in < 500 ms."""

    async def _run() -> dict:
        with patch("src.agents.nodes.intent._chain") as mock_chain:
            mock_chain.ainvoke = AsyncMock(return_value=_MOCK_RESULT)
            # Import inside the patch context so the mock is applied correctly
            from src.agents.nodes.intent import intent_node  # noqa: PLC0415

            return await intent_node(
                {
                    "request_id": "bench-req",
                    "user_id": "bench-user",
                    "username": "benchmarker",
                    "roles": ["user"],
                    "tool_name": "search",
                    "prompt": PROMPT_2000_TOKENS,
                    "timestamp": "2026-01-01T00:00:00Z",
                    "status": "running",
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
            )

    result = benchmark(lambda: asyncio.run(_run()))
    assert result["intent_type"] == "debugging"
    assert result["intent_confidence"] == pytest.approx(0.92)
