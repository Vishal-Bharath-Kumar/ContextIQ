"""
Unit tests for TASK-US005-02: Agent Worker ``POST /v1/execute`` endpoint.

Coverage targets (≥ 90% on routers/execute.py):
  - Valid dispatch: returns HTTP 200 ExecuteResponse with status="success"
  - request_id echoed from ExecuteRequest to ExecuteResponse
  - initial_state.status is PENDING at moment of graph invocation
  - initial_state.timestamp is a valid ISO-8601 UTC string
  - initial_state.prompt defaults to "" when "prompt" absent from arguments
  - initial_state.prompt set from arguments["prompt"] when present
  - graph exception returns HTTP 200 with status="error" (not HTTP 500)
  - GET /healthz returns {"status": "ok", "graph_compiled": true}
  - GET /healthz returns graph_compiled=false when graph not set
  - Missing required field in ExecuteRequest returns HTTP 422
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.agent_worker.routers.execute import get_graph, router, set_graph
from src.agent_worker.schemas.execute_types import ExecuteRequest, ExecuteResponse, ToolCallError
from src.agents.state import AgentState, ExecutionStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ISO8601_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)

_SAMPLE_REQUEST = {
    "request_id": "11111111-1111-4111-8111-111111111111",
    "user_id": "user-sub-001",
    "username": "alice",
    "roles": ["developer"],
    "tool_name": "context_search",
    "arguments": {"prompt": "What is the auth flow?"},
    "trace_id": "a" * 32,
}

_FINAL_STATE: AgentState = {
    "request_id": "11111111-1111-4111-8111-111111111111",
    "user_id": "user-sub-001",
    "username": "alice",
    "roles": ["developer"],
    "tool_name": "context_search",
    "prompt": "What is the auth flow?",
    "timestamp": "2026-07-16T00:00:00Z",
    "status": ExecutionStatus.COMPLETE,
    "current_node": "routing_agent",
    "error": None,
    "intent_type": "question_answering",
    "intent_confidence": 0.95,
    "execution_plan": None,
    "raw_context": None,
    "ranked_context": None,
    "compressed_context": None,
    "tokens_before_compression": None,
    "tokens_after_compression": None,
    "governance_decisions": None,
    "redacted_chunks": None,
    "selected_model": "gpt-4o",
    "model_routing_score": 0.9,
    "final_response": {"answer": "The auth flow uses Keycloak."},
}


def _make_mock_graph(
    final_state: AgentState | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Return a mock CompiledStateGraph."""
    graph = MagicMock()
    if raise_exc is not None:
        graph.ainvoke = AsyncMock(side_effect=raise_exc)
    else:
        graph.ainvoke = AsyncMock(return_value=final_state or _FINAL_STATE)
    return graph


# ---------------------------------------------------------------------------
# App fixture — reset _compiled_graph between tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_client_with_graph():
    """Return a TestClient with a mock graph injected."""
    import src.agent_worker.routers.execute as execute_module
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    mock_graph = _make_mock_graph()
    # Override the dependency AND set the module-level variable so /healthz works.
    app.dependency_overrides[get_graph] = lambda: mock_graph
    set_graph(mock_graph)
    yield TestClient(app), mock_graph
    app.dependency_overrides.clear()
    # Reset the module-level graph after each test.
    execute_module._compiled_graph = None


@pytest.fixture()
def test_client_no_graph():
    """Return a TestClient backed by the real get_graph (no override) and no graph set."""
    from fastapi import FastAPI

    # Ensure no graph is registered for this test
    with patch("src.agent_worker.routers.execute._compiled_graph", None):
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Tests — /v1/execute
# ---------------------------------------------------------------------------

def test_valid_dispatch_returns_success(test_client_with_graph):
    client, mock_graph = test_client_with_graph
    resp = client.post("/v1/execute", json=_SAMPLE_REQUEST)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["request_id"] == _SAMPLE_REQUEST["request_id"]
    assert body["output"]["answer"] == "The auth flow uses Keycloak."
    assert body["output"]["degraded_sources"] == []
    assert body["error"] is None
    assert isinstance(body["duration_ms"], int)
    assert body["duration_ms"] >= 0


def test_request_id_echoed_in_response(test_client_with_graph):
    client, _ = test_client_with_graph
    custom_id = "22222222-2222-4222-8222-222222222222"
    payload = {**_SAMPLE_REQUEST, "request_id": custom_id}
    resp = client.post("/v1/execute", json=payload)

    assert resp.status_code == 200
    assert resp.json()["request_id"] == custom_id


def test_initial_state_status_is_pending(test_client_with_graph):
    """Verify graph.ainvoke receives an initial_state with status=PENDING."""
    client, mock_graph = test_client_with_graph
    client.post("/v1/execute", json=_SAMPLE_REQUEST)

    # Extract the positional argument (initial_state) passed to ainvoke
    call_args = mock_graph.ainvoke.call_args
    initial_state = call_args[0][0]  # first positional arg

    assert initial_state["status"] == ExecutionStatus.PENDING


def test_initial_state_timestamp_is_iso8601_utc(test_client_with_graph):
    """Verify timestamp is a valid ISO-8601 UTC string set at request time."""
    client, mock_graph = test_client_with_graph
    before = datetime.now(UTC)
    client.post("/v1/execute", json=_SAMPLE_REQUEST)
    after = datetime.now(UTC)

    call_args = mock_graph.ainvoke.call_args
    initial_state = call_args[0][0]
    ts_str: str = initial_state["timestamp"]

    assert _ISO8601_UTC_RE.match(ts_str), f"Not ISO-8601 UTC: {ts_str!r}"

    # Parse and check it falls within the request window
    parsed = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    assert before <= parsed <= after


def test_prompt_set_from_arguments(test_client_with_graph):
    """Verify prompt is populated from arguments["prompt"]."""
    client, mock_graph = test_client_with_graph
    payload = {**_SAMPLE_REQUEST, "arguments": {"prompt": "Tell me about RBAC"}}
    client.post("/v1/execute", json=payload)

    initial_state = mock_graph.ainvoke.call_args[0][0]
    assert initial_state["prompt"] == "Tell me about RBAC"


def test_prompt_defaults_to_empty_string_when_missing(test_client_with_graph):
    """Verify prompt defaults to '' when 'prompt' key absent from arguments."""
    client, mock_graph = test_client_with_graph
    payload = {**_SAMPLE_REQUEST, "arguments": {"filter": "recent"}}
    client.post("/v1/execute", json=payload)

    initial_state = mock_graph.ainvoke.call_args[0][0]
    assert initial_state["prompt"] == ""


def test_graph_exception_returns_error_not_http_500(test_client_with_graph):
    """Graph exception must yield HTTP 200 with status='error', not HTTP 500."""
    client, mock_graph = test_client_with_graph
    mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("Pipeline exploded"))

    resp = client.post("/v1/execute", json=_SAMPLE_REQUEST)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert body["request_id"] == _SAMPLE_REQUEST["request_id"]
    assert body["output"] is None
    assert body["error"]["code"] == -32603
    assert isinstance(body["duration_ms"], int)


def test_graph_exception_preserves_request_id_in_error(test_client_with_graph):
    client, mock_graph = test_client_with_graph
    mock_graph.ainvoke = AsyncMock(side_effect=ValueError("bad state"))
    custom_id = "33333333-3333-4333-8333-333333333333"
    payload = {**_SAMPLE_REQUEST, "request_id": custom_id}

    resp = client.post("/v1/execute", json=payload)
    assert resp.json()["request_id"] == custom_id


def test_missing_required_field_returns_422(test_client_with_graph):
    """ExecuteRequest validation: missing 'tool_name' returns HTTP 422."""
    client, _ = test_client_with_graph
    payload = {k: v for k, v in _SAMPLE_REQUEST.items() if k != "tool_name"}

    resp = client.post("/v1/execute", json=payload)
    assert resp.status_code == 422


def test_config_uses_request_id_as_thread_id(test_client_with_graph):
    """LangGraph config must pass request_id as thread_id for checkpoint isolation."""
    client, mock_graph = test_client_with_graph
    client.post("/v1/execute", json=_SAMPLE_REQUEST)

    call_kwargs = mock_graph.ainvoke.call_args[1]  # keyword args
    config = call_kwargs.get("config", {})
    assert config["configurable"]["thread_id"] == _SAMPLE_REQUEST["request_id"]


# ---------------------------------------------------------------------------
# Tests — GET /healthz
# ---------------------------------------------------------------------------

def test_healthz_returns_ok_when_graph_compiled(test_client_with_graph):
    client, _ = test_client_with_graph
    resp = client.get("/healthz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["graph_compiled"] is True


def test_execute_raises_500_when_graph_not_initialised():
    """GET /v1/execute returns HTTP 500 if get_graph raises RuntimeError (no graph set)."""
    import src.agent_worker.routers.execute as execute_module
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    # Ensure no graph is set — do NOT override the dependency
    prev = execute_module._compiled_graph
    execute_module._compiled_graph = None
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/v1/execute", json=_SAMPLE_REQUEST)
        assert resp.status_code == 500
    finally:
        execute_module._compiled_graph = prev


def test_healthz_returns_graph_compiled_false_when_no_graph():
    """GET /healthz should still return 200 even when graph not compiled."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    with patch("src.agent_worker.routers.execute._compiled_graph", None):
        with TestClient(app) as client:
            resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json()["graph_compiled"] is False
