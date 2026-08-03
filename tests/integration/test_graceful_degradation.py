"""End-to-end graceful-degradation integration tests — TASK-US008-05.

Verifies the full connector-dispatch path:
  - One connector failing → HTTP 200 with partial context and degraded_sources.
  - All connectors failing → HTTP 200 with empty context (never HTTP 500).
  - Circuit breaker opens after 5 consecutive failures; subsequent request reports
    ConnectorCircuitOpenError; Prometheus gauge reflects open state (== 1.0).

Architecture
------------
A lightweight FastAPI test app is built per test session.  It wires the real
:class:`~src.agents.retrieval.parallel_dispatcher.ParallelConnectorDispatcher`
and :class:`~src.agents.retrieval.connector_circuit_breaker.ConnectorCircuitBreakerRegistry`
directly into a thin ``POST /v1/execute`` handler, exercising the same connector
dispatch and circuit-breaker logic as the production pipeline without requiring
Redis, Kafka, or the full LangGraph graph.

Run:
    pytest tests/integration/test_graceful_degradation.py -v
    pytest -m integration tests/integration/test_graceful_degradation.py -v
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.agent_worker.schemas.execute_types import ExecuteRequest, ExecuteResponse
from src.agents.retrieval.connector_circuit_breaker import ConnectorCircuitBreakerRegistry
from src.agents.retrieval.connector_registry import ConnectorRegistry
from src.agents.retrieval.parallel_dispatcher import ParallelConnectorDispatcher
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GITHUB_SOURCE_ID = "github:test-org/test-repo"
_CONFLUENCE_SOURCE_ID = "confluence:ENG"
_FETCHED_AT = datetime(2026, 7, 16, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_result(source_id: str, content: str = "test content") -> ConnectorResult:
    return ConnectorResult(
        source_id=source_id,
        content=content,
        metadata=ResultMetadata(source_url=f"https://example.com/{source_id}"),
        fetched_at=_FETCHED_AT,
    )


def _make_connector(source_id: str, content: str = "test content") -> MagicMock:
    """Return a healthy mock connector that returns a single result."""
    connector = MagicMock()
    connector.fetch = AsyncMock(return_value=[_make_result(source_id, content)])
    return connector


def make_execute_request(
    sources: list[str],
    prompt: str,
    request_id: str | None = None,
) -> dict:
    """Build a minimal ExecuteRequest payload suitable for the integration test app."""
    return {
        "request_id": request_id or str(uuid.uuid4()),
        "user_id": "integration-test-user",
        "username": "test",
        "roles": ["developer"],
        "tool_name": "context_search",
        "arguments": {"sources": sources, "prompt": prompt},
        "trace_id": "0" * 32,
    }


def _make_test_app(
    connector_registry: ConnectorRegistry,
    circuit_breaker_registry: ConnectorCircuitBreakerRegistry,
) -> FastAPI:
    """Build a minimal FastAPI app that exercises the real connector dispatch.

    The handler extracts ``sources`` and ``prompt`` from ``arguments``, runs the
    :class:`~src.agents.retrieval.parallel_dispatcher.ParallelConnectorDispatcher`,
    and returns an :class:`~src.agent_worker.schemas.execute_types.ExecuteResponse`
    with ``output.context`` and ``output.degraded_sources`` populated.
    """
    app = FastAPI()

    @app.post("/v1/execute", response_model=ExecuteResponse)
    async def execute(req: ExecuteRequest) -> ExecuteResponse:
        sources: list[str] = req.arguments.get("sources", [])
        prompt: str = req.arguments.get("prompt", "")

        dispatcher = ParallelConnectorDispatcher(
            connector_registry=connector_registry,
            timeout_seconds=2.0,
            breaker_registry=circuit_breaker_registry,
        )
        result = await dispatcher.fetch_all(
            query=prompt,
            source_ids=sources,
            token_budget_per_source={},
        )

        context_chunks = [
            {
                "chunk_id": f"chunk-{i}",
                "content": chunk.content,
                "source_id": chunk.source_id,
            }
            for i, chunk in enumerate(result.chunks)
        ]

        return ExecuteResponse(
            request_id=req.request_id,
            status="success",
            output={
                "context": context_chunks,
                "degraded_sources": [
                    {
                        "source_id": fs.source_id,
                        "error_type": fs.error_type,
                        "message": fs.message,
                    }
                    for fs in result.failed_sources
                ],
            },
            duration_ms=0,
        )

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def connector_registry() -> ConnectorRegistry:
    """Fresh ConnectorRegistry with one GitHub and one Confluence connector."""
    registry = ConnectorRegistry()
    registry.register(
        _GITHUB_SOURCE_ID,
        _make_connector(_GITHUB_SOURCE_ID, "GitHub: auth service uses service accounts"),
    )
    registry.register(
        _CONFLUENCE_SOURCE_ID,
        _make_connector(_CONFLUENCE_SOURCE_ID, "Confluence: auth flow overview"),
    )
    return registry


@pytest.fixture
def circuit_breaker_registry() -> ConnectorCircuitBreakerRegistry:
    """Fresh ConnectorCircuitBreakerRegistry with fail_max=5 and a long reset timeout."""
    reg = ConnectorCircuitBreakerRegistry.__new__(ConnectorCircuitBreakerRegistry)
    reg._breakers = {}
    # Instance attributes shadow the class-level defaults so each test is isolated.
    reg.FAIL_MAX = 5
    reg.RESET_TIMEOUT = 3600  # keep circuit open throughout the test
    return reg


@pytest.fixture
def prometheus_registry() -> object:
    """Return the global Prometheus REGISTRY for circuit-breaker state assertions."""
    from prometheus_client import REGISTRY  # noqa: PLC0415

    return REGISTRY


@pytest_asyncio.fixture
async def agent_worker_client(
    connector_registry: ConnectorRegistry,
    circuit_breaker_registry: ConnectorCircuitBreakerRegistry,
) -> AsyncClient:
    """AsyncClient connected to the lightweight test app."""
    app = _make_test_app(connector_registry, circuit_breaker_registry)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_partial_context_returned_when_one_connector_fails(
    agent_worker_client: AsyncClient,
    connector_registry: ConnectorRegistry,
) -> None:
    """One connector fails → HTTP 200, Confluence context present, GitHub degraded."""
    github_connector = connector_registry.get(_GITHUB_SOURCE_ID)
    github_connector.fetch = AsyncMock(side_effect=ConnectionError("GitHub down"))

    response = await agent_worker_client.post(
        "/v1/execute",
        json=make_execute_request(
            sources=[_GITHUB_SOURCE_ID, _CONFLUENCE_SOURCE_ID],
            prompt="How does the auth service work?",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert len(body["output"]["context"]) > 0  # Confluence results present
    assert len(body["output"]["degraded_sources"]) == 1
    assert body["output"]["degraded_sources"][0]["source_id"] == _GITHUB_SOURCE_ID
    assert body["output"]["degraded_sources"][0]["error_type"] == "ConnectionError"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_all_connectors_down_returns_200_with_empty_context(
    agent_worker_client: AsyncClient,
    connector_registry: ConnectorRegistry,
) -> None:
    """All connectors fail → HTTP 200, empty context, all sources in degraded_sources."""
    active_ids = connector_registry.active_source_ids()
    for source_id in active_ids:
        connector_registry.get(source_id).fetch = AsyncMock(side_effect=Exception("down"))

    response = await agent_worker_client.post(
        "/v1/execute",
        json=make_execute_request(
            sources=active_ids,
            prompt="Any prompt",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["output"]["context"] == []
    assert len(body["output"]["degraded_sources"]) == len(active_ids)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_circuit_breaker_opens_after_5_failures(
    agent_worker_client: AsyncClient,
    connector_registry: ConnectorRegistry,
    circuit_breaker_registry: ConnectorCircuitBreakerRegistry,
    prometheus_registry: object,
) -> None:
    """5 consecutive fetch failures open the circuit; 6th request reports ConnectorCircuitOpenError."""
    github = connector_registry.get(_GITHUB_SOURCE_ID)
    github.fetch = AsyncMock(side_effect=Exception("server error"))

    # Trigger 5 consecutive failures — circuit should open on the 5th.
    for _ in range(5):
        await agent_worker_client.post(
            "/v1/execute",
            json=make_execute_request(sources=[_GITHUB_SOURCE_ID], prompt="test"),
        )

    # 6th request: circuit is open → connector skipped with ConnectorCircuitOpenError.
    response = await agent_worker_client.post(
        "/v1/execute",
        json=make_execute_request(sources=[_GITHUB_SOURCE_ID], prompt="test"),
    )
    body = response.json()
    assert body["output"]["degraded_sources"][0]["error_type"] == "ConnectorCircuitOpenError"

    # Prometheus gauge must reflect the open state (0=closed, 1=open, 2=half-open).
    state = prometheus_registry.get_sample_value(
        "contextiq_connector_circuit_breaker_state",
        {"connector_id": _GITHUB_SOURCE_ID},
    )
    assert state == 1.0
