"""Unit tests for llm_metrics_node and Prometheus LLM cost metrics (TASK-US037-03).

Coverage:
  - AC-1: contextiq_llm_cost_usd_total increments by cost_usd
  - AC-1: contextiq_llm_tokens_total{token_type="prompt"} increments by prompt_tokens
  - AC-1: contextiq_llm_tokens_total{token_type="completion"} increments by completion_tokens
  - AC-6: all five label dimensions present (service, model_id, team_id, tenant_id, intent_type)
  - _compute_cost() returns 0.0 without raising for unknown models
  - LLMCostRecorder.record_llm_call() called once via asyncio.create_task()
  - llm_cost_usd is present in the returned AgentState
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.observability.cost.llm_metrics import (
    _compute_cost,
    _get_request_id,
    llm_metrics_node,
    set_llm_cost_recorder,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQ_ID = uuid.uuid4()
_NOW = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)


def _make_state(**overrides: Any) -> dict:
    base: dict = {
        "request_id": str(_REQ_ID),
        "model_selected": "gpt-4o",
        "prompt_tokens": 200,
        "completion_tokens": 80,
        "jwt_claims": {"sub": "user-abc", "team_id": "team-alpha"},
        "team_id": "team-alpha",
        "tenant_id": "tenant-001",
        "intent_type": "query",
        "status": "running",
        "user_id": "user-abc",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _compute_cost
# ---------------------------------------------------------------------------


class TestComputeCost:
    def test_returns_float_for_known_model(self) -> None:
        """LiteLLM can compute cost for gpt-4o without raising."""
        with patch("litellm.completion_cost", return_value=0.005) as mock_cc:
            result = _compute_cost("gpt-4o", 100, 50)
        mock_cc.assert_called_once_with(
            model="gpt-4o", prompt_tokens=100, completion_tokens=50
        )
        assert result == round(0.005, 8)

    def test_returns_zero_for_unknown_model(self) -> None:
        """Falls back to 0.0 without raising when model not in cost map."""
        with patch("litellm.completion_cost", side_effect=Exception("unknown model")):
            result = _compute_cost("unknown-model-xyz", 100, 50)
        assert result == 0.0

    def test_returns_zero_when_litellm_unavailable(self) -> None:
        """Falls back to 0.0 without raising when litellm import fails."""
        import sys

        real_modules = sys.modules.copy()
        sys.modules["litellm"] = None  # type: ignore[assignment]
        try:
            result = _compute_cost("gpt-4o", 100, 50)
        finally:
            sys.modules.update(real_modules)
        assert result == 0.0


# ---------------------------------------------------------------------------
# _get_request_id
# ---------------------------------------------------------------------------


class TestGetRequestId:
    def test_parses_uuid_string(self) -> None:
        state = {"request_id": str(_REQ_ID)}
        assert _get_request_id(state) == _REQ_ID  # type: ignore[arg-type]

    def test_passes_through_uuid_object(self) -> None:
        state = {"request_id": _REQ_ID}
        assert _get_request_id(state) == _REQ_ID  # type: ignore[arg-type]

    def test_generates_uuid_when_missing(self) -> None:
        state: dict = {}
        result = _get_request_id(state)  # type: ignore[arg-type]
        assert isinstance(result, uuid.UUID)

    def test_generates_uuid_for_invalid_string(self) -> None:
        state = {"request_id": "not-a-uuid"}
        result = _get_request_id(state)  # type: ignore[arg-type]
        assert isinstance(result, uuid.UUID)


# ---------------------------------------------------------------------------
# Prometheus counter increments (AC-1)
# ---------------------------------------------------------------------------


class TestPrometheusIncrements:
    async def test_cost_counter_incremented(self) -> None:
        """contextiq_llm_cost_usd_total increments by computed cost_usd (AC-1)."""
        state = _make_state()
        expected_cost = 0.0042

        with (
            patch(
                "src.observability.cost.llm_metrics._compute_cost",
                return_value=expected_cost,
            ),
            patch(
                "src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"
            ) as mock_cost_counter,
            patch(
                "src.observability.cost.llm_metrics.contextiq_llm_tokens_total"
            ),
            patch("asyncio.create_task"),
        ):
            mock_child = MagicMock()
            mock_cost_counter.labels.return_value = mock_child
            await llm_metrics_node(state)  # type: ignore[arg-type]

        mock_cost_counter.labels.assert_called_once_with(
            service="contextiq-api",
            model_id="gpt-4o",
            team_id="team-alpha",
            tenant_id="tenant-001",
            intent_type="query",
        )
        mock_child.inc.assert_called_once_with(expected_cost)

    async def test_prompt_token_counter_incremented(self) -> None:
        """contextiq_llm_tokens_total{token_type="prompt"} increments by prompt_tokens (AC-1)."""
        state = _make_state(prompt_tokens=150)

        with (
            patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.0),
            patch("src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"),
            patch(
                "src.observability.cost.llm_metrics.contextiq_llm_tokens_total"
            ) as mock_tok_counter,
            patch("asyncio.create_task"),
        ):
            mock_child = MagicMock()
            mock_tok_counter.labels.return_value = mock_child
            await llm_metrics_node(state)  # type: ignore[arg-type]

        mock_tok_counter.labels.assert_any_call(
            service="contextiq-api",
            model_id="gpt-4o",
            team_id="team-alpha",
            tenant_id="tenant-001",
            intent_type="query",
            token_type="prompt",
        )
        calls = [c.args[0] for c in mock_child.inc.call_args_list]
        assert 150 in calls

    async def test_completion_token_counter_incremented(self) -> None:
        """contextiq_llm_tokens_total{token_type="completion"} increments by completion_tokens (AC-1)."""
        state = _make_state(completion_tokens=60)

        with (
            patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.0),
            patch("src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"),
            patch(
                "src.observability.cost.llm_metrics.contextiq_llm_tokens_total"
            ) as mock_tok_counter,
            patch("asyncio.create_task"),
        ):
            mock_child = MagicMock()
            mock_tok_counter.labels.return_value = mock_child
            await llm_metrics_node(state)  # type: ignore[arg-type]

        mock_tok_counter.labels.assert_any_call(
            service="contextiq-api",
            model_id="gpt-4o",
            team_id="team-alpha",
            tenant_id="tenant-001",
            intent_type="query",
            token_type="completion",
        )
        calls = [c.args[0] for c in mock_child.inc.call_args_list]
        assert 60 in calls

    async def test_all_five_label_dimensions_present(self) -> None:
        """All five AC-6 label dimensions appear on cost counter call."""
        state = _make_state(
            model_selected="claude-3-opus",
            team_id="team-beta",
            tenant_id="tenant-xyz",
            intent_type="summarise",
        )

        with (
            patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.0),
            patch(
                "src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"
            ) as mock_cost_counter,
            patch("src.observability.cost.llm_metrics.contextiq_llm_tokens_total"),
            patch("asyncio.create_task"),
        ):
            mock_child = MagicMock()
            mock_cost_counter.labels.return_value = mock_child
            await llm_metrics_node(state)  # type: ignore[arg-type]

        _, kwargs = mock_cost_counter.labels.call_args
        assert set(kwargs.keys()) == {"service", "model_id", "team_id", "tenant_id", "intent_type"}
        assert kwargs["service"] == "contextiq-api"
        assert kwargs["model_id"] == "claude-3-opus"
        assert kwargs["team_id"] == "team-beta"
        assert kwargs["tenant_id"] == "tenant-xyz"
        assert kwargs["intent_type"] == "summarise"


# ---------------------------------------------------------------------------
# Langfuse fire-and-forget (AC-4)
# ---------------------------------------------------------------------------


class TestLangfuseFireAndForget:
    async def test_create_task_called_when_recorder_present(self) -> None:
        """asyncio.create_task is invoked once when a recorder is available (AC-4)."""
        mock_recorder = MagicMock()
        state = _make_state()
        state["_config"] = {"llm_cost_recorder": mock_recorder}

        with (
            patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.001),
            patch("src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"),
            patch("src.observability.cost.llm_metrics.contextiq_llm_tokens_total"),
            patch("asyncio.create_task") as mock_create_task,
        ):
            await llm_metrics_node(state)  # type: ignore[arg-type]

        mock_create_task.assert_called_once()
        task_name: str = mock_create_task.call_args.kwargs.get("name", "")
        assert task_name.startswith("llm_cost_")

    async def test_no_task_when_no_recorder(self) -> None:
        """asyncio.create_task is NOT called when no recorder is configured."""
        # Ensure global recorder is cleared
        set_llm_cost_recorder(None)  # type: ignore[arg-type]
        state = _make_state()

        with (
            patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.0),
            patch("src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"),
            patch("src.observability.cost.llm_metrics.contextiq_llm_tokens_total"),
            patch("asyncio.create_task") as mock_create_task,
        ):
            await llm_metrics_node(state)  # type: ignore[arg-type]

        mock_create_task.assert_not_called()

    async def test_write_langfuse_calls_record_llm_call(self) -> None:
        """_write_langfuse() invokes recorder.record_llm_call() exactly once."""
        from src.observability.cost.llm_metrics import _write_langfuse
        from src.observability.cost.schemas import LLMCallRecord

        mock_recorder = MagicMock()
        record = LLMCallRecord(
            request_id=_REQ_ID,
            tenant_id="tenant-001",
            model_id="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.005,
            user_id="user-abc",
            team_id="team-alpha",
            intent_type="query",
            timestamp=_NOW,
        )

        await _write_langfuse(mock_recorder, record)

        mock_recorder.record_llm_call.assert_called_once_with(record)

    async def test_write_langfuse_swallows_exceptions(self) -> None:
        """_write_langfuse() never raises even if recorder raises."""
        from src.observability.cost.llm_metrics import _write_langfuse
        from src.observability.cost.schemas import LLMCallRecord

        mock_recorder = MagicMock()
        mock_recorder.record_llm_call.side_effect = RuntimeError("boom")
        record = LLMCallRecord(
            request_id=_REQ_ID,
            tenant_id="tenant-001",
            model_id="gpt-4o",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.0,
            user_id="u",
            team_id="t",
            timestamp=_NOW,
        )
        # Must not raise
        await _write_langfuse(mock_recorder, record)


# ---------------------------------------------------------------------------
# State output
# ---------------------------------------------------------------------------


class TestStateOutput:
    async def test_llm_cost_usd_in_returned_state(self) -> None:
        """llm_cost_usd is set in the returned AgentState (AC-7 / trace_writer contract)."""
        state = _make_state()

        with (
            patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.0099),
            patch("src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"),
            patch("src.observability.cost.llm_metrics.contextiq_llm_tokens_total"),
            patch("asyncio.create_task"),
        ):
            result = await llm_metrics_node(state)  # type: ignore[arg-type]

        assert result["llm_cost_usd"] == 0.0099

    async def test_existing_state_keys_preserved(self) -> None:
        """Node returns a superset of the input state (no keys dropped)."""
        state = _make_state(extra_key="should-survive")

        with (
            patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.0),
            patch("src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"),
            patch("src.observability.cost.llm_metrics.contextiq_llm_tokens_total"),
            patch("asyncio.create_task"),
        ):
            result = await llm_metrics_node(state)  # type: ignore[arg-type]

        assert result["extra_key"] == "should-survive"

    async def test_defaults_used_when_state_fields_absent(self) -> None:
        """Node does not raise when optional state fields are missing."""
        minimal_state: dict = {
            "request_id": str(uuid.uuid4()),
            "status": "running",
            "user_id": "u",
        }

        with (
            patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.0),
            patch("src.observability.cost.llm_metrics.contextiq_llm_cost_usd_total"),
            patch("src.observability.cost.llm_metrics.contextiq_llm_tokens_total"),
            patch("asyncio.create_task"),
        ):
            result = await llm_metrics_node(minimal_state)  # type: ignore[arg-type]

        assert "llm_cost_usd" in result
