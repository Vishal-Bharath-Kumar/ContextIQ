"""Integration tests for llm_metrics_node — AC-1 and AC-3 (TASK-US037-05).

Coverage:
  - AC-1/AC-3: contextiq_llm_cost_usd_total incremented by computed cost
  - AC-3: llm_cost_usd key is present in the returned AgentState
  - AC-1: all five label dimensions are set correctly on cost counter
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.observability.cost.llm_metrics import (
    llm_metrics_node,
    set_llm_cost_recorder,
)
from src.observability.cost.recorder import LLMCostRecorder
from tests.observability.conftest import TEAM_ID, TENANT_ID, REQUEST_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_STATE = {
    "request_id": str(REQUEST_ID),
    "tenant_id": TENANT_ID,
    "team_id": TEAM_ID,
    "jwt_claims": {"sub": "user-abc123"},
    "intent": "technical_support",
    "model_selected": "gpt-4o",
    "prompt_tokens": 512,
    "completion_tokens": 128,
}


# ---------------------------------------------------------------------------
# AC-3: Prometheus cost counter incremented by llm_metrics_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_metrics_node_increments_cost_counter():
    """AC-3: contextiq_llm_cost_usd_total increments after llm_metrics_node runs."""
    mock_rec = MagicMock(spec=LLMCostRecorder)
    set_llm_cost_recorder(mock_rec)

    labels = {
        "service": "contextiq-api",
        "model_id": "gpt-4o",
        "team_id": TEAM_ID,
        "tenant_id": TENANT_ID,
        "intent_type": "technical_support",
    }

    with (
        patch(
            "src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"
        ) as mock_cost_counter,
        patch("src.observability.cost.llm_metrics.contextiq_llm_tokens_total"),
        patch("asyncio.create_task"),
        patch(
            "src.observability.cost.llm_metrics._compute_cost", return_value=0.00480
        ),
    ):
        mock_child = MagicMock()
        mock_cost_counter.labels.return_value = mock_child

        await llm_metrics_node(_BASE_STATE)  # type: ignore[arg-type]

    mock_cost_counter.labels.assert_called_once_with(**labels)
    mock_child.inc.assert_called_once_with(0.00480)


@pytest.mark.asyncio
async def test_llm_metrics_node_exposes_llm_cost_usd_in_state():
    """AC-3: llm_cost_usd added to returned AgentState."""
    set_llm_cost_recorder(MagicMock(spec=LLMCostRecorder))

    state = {
        "request_id": str(REQUEST_ID),
        "tenant_id": TENANT_ID,
        "model_selected": "gpt-4o",
        "prompt_tokens": 100,
        "completion_tokens": 50,
    }

    with (
        patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.001),
        patch("src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"),
        patch("src.observability.cost.llm_metrics.contextiq_llm_tokens_total"),
        patch("asyncio.create_task"),
    ):
        result = await llm_metrics_node(state)  # type: ignore[arg-type]

    assert "llm_cost_usd" in result
    assert abs(result["llm_cost_usd"] - 0.001) < 1e-9


@pytest.mark.asyncio
async def test_llm_metrics_node_all_five_label_dimensions_present():
    """AC-1: all five label dimensions are set on the cost counter call."""
    set_llm_cost_recorder(MagicMock(spec=LLMCostRecorder))

    state = {
        "request_id": str(uuid.uuid4()),
        "tenant_id": "tenant-x",
        "team_id": "team-y",
        "jwt_claims": {"sub": "user-z"},
        "intent_type": "summarise",
        "model_selected": "claude-3-opus",
        "prompt_tokens": 200,
        "completion_tokens": 80,
    }

    with (
        patch(
            "src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"
        ) as mock_counter,
        patch("src.observability.cost.llm_metrics.contextiq_llm_tokens_total"),
        patch("asyncio.create_task"),
        patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.0),
    ):
        mock_counter.labels.return_value = MagicMock()
        await llm_metrics_node(state)  # type: ignore[arg-type]

    _, kwargs = mock_counter.labels.call_args
    assert set(kwargs.keys()) == {"service", "model_id", "team_id", "tenant_id", "intent_type"}
    assert kwargs["service"] == "contextiq-api"
    assert kwargs["model_id"] == "claude-3-opus"
    assert kwargs["team_id"] == "team-y"
    assert kwargs["tenant_id"] == "tenant-x"
    assert kwargs["intent_type"] == "summarise"
