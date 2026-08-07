from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

_fake_langfuse = types.ModuleType("langfuse")
_fake_langfuse.Langfuse = object
_fake_langfuse.version = types.SimpleNamespace(__version__="0.0.0")
sys.modules.setdefault("langfuse", _fake_langfuse)

from src.agents.nodes.llm_response import llm_response_node
from src.agents.state import ExecutionStatus
from src.governance.nodes.opa_filter_node import opa_filter_node


@pytest.mark.asyncio
async def test_opa_filter_node_does_not_return_runtime_config_on_empty_context() -> None:
    state = {
        "request_id": "req-1",
        "user_id": "user-1",
        "username": "admin",
        "roles": ["admin"],
        "tool_name": "context_query",
        "prompt": "describe the system",
        "timestamp": "2026-08-03T00:00:00Z",
        "status": ExecutionStatus.RUNNING,
        "current_node": "governance_agent",
        "error": None,
        "ranked_context": [],
        "execution_trace": [],
        "_config": {"routing_runtime": object()},
    }

    result = await opa_filter_node(state)

    assert result["current_node"] == "opa_filter"
    assert result["status"] == ExecutionStatus.RUNNING
    assert "_config" not in result
    assert result["opa_decisions"] == []


@pytest.mark.asyncio
async def test_llm_response_node_degrades_on_invocation_exception() -> None:
    runtime_services = SimpleNamespace(
        fallback_invoker=SimpleNamespace(
            invoke=AsyncMock(side_effect=RuntimeError("provider unavailable")),
        ),
        get_model_definition=AsyncMock(return_value=None),
    )
    state = {
        "request_id": "req-1",
        "user_id": "user-1",
        "username": "admin",
        "roles": ["admin"],
        "tool_name": "context_query",
        "prompt": "describe the system",
        "timestamp": "2026-08-03T00:00:00Z",
        "status": ExecutionStatus.RUNNING,
        "current_node": "routing_agent",
        "error": None,
        "intent_type": "architecture",
        "intent_confidence": 0.9,
        "selected_model": "gpt-4o-mini",
        "fallback_chain": ["gpt-4o-mini"],
        "final_response": {
            "type": "context_package",
            "context": [{"source_id": "github", "path": "src/main.py", "content": "create_app"}],
            "degraded_sources": [],
        },
        "_config": {"routing_runtime": runtime_services},
    }

    result = await llm_response_node(state)

    assert result["status"] == ExecutionStatus.COMPLETE
    assert result["current_node"] == "llm_response_agent"
    assert result["final_response"]["invocation_error"] == "provider unavailable"
    assert result["final_response"]["degraded_sources"][0]["source_id"] == "llm-response"