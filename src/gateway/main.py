"""
FastAPI application factory for the ContextIQ MCP Gateway.

TASK-US001-01: Mounts SSE (GET {mcp_path}/sse) and WebSocket (WS {mcp_path}/ws)
transports.  The endpoint prefix is read from CONTEXTIQ_MCP_PATH (default: /mcp).

Transport overview
------------------
* SSE   — backed by FastMCP's ``http_app(transport="sse")`` ASGI sub-application.
* WS    — custom FastAPI WebSocket route that bridges the connection to the
          underlying ``mcp.server.Server`` via ``anyio`` memory-object streams.
          This satisfies clients that prefer a persistent bidirectional channel
          over SSE + HTTP POST.

Startup
-------
::

    uvicorn src.gateway.main:app --workers 1 --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter

from src.connector_sdk.health_poller import ConnectorHealthPoller
from src.connector_sdk.registry import ConnectorRegistry
from src.gateway.config import settings
from src.gateway.lifespan import start_cache_invalidation_subscriber
from src.gateway.middleware.circuit_breaker import CircuitBreakerMiddleware
from src.gateway.middleware.context_middleware import RequestContextMiddleware
from src.gateway.middleware.error_handler import ErrorHandlerMiddleware
from src.gateway.middleware.jwt_auth import JWTAuthMiddleware
from src.gateway.middleware.tracing import ConnectionTracingMiddleware
from src.gateway.mcp_server import mcp, sse_app
from src.gateway.state import circuit_state_gauge, gateway_breaker
from src.gateway.telemetry import setup_telemetry
from src.registry.cache.tool_cache import ToolListCache

logger = logging.getLogger(__name__)

# TypeAdapter for (de)serialising JSONRPCMessage at runtime.
# Imported lazily to avoid a hard dependency on `mcp` at module import time
# when mocked in unit tests.
try:
    from mcp.shared.message import SessionMessage as _SessionMessage
    from mcp.types import JSONRPCMessage as _JSONRPCMessage

    _msg_ta: TypeAdapter[Any] = TypeAdapter(_JSONRPCMessage)
except ImportError:  # pragma: no cover — only absent in stripped test envs
    _SessionMessage = None  # type: ignore[assignment,misc]
    _msg_ta = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_gateway_app(jwks_client: Any = None) -> FastAPI:
    """
    Build and return the FastAPI gateway application.

    Separated from the module-level singleton so tests can instantiate a fresh
    app without side-effects from previous test runs.

    Parameters
    ----------
    jwks_client:
        Optional pre-started :class:`~src.auth.jwks_client.JWKSClient`.
        When supplied, ``JWTAuthMiddleware`` is registered outermost in the
        middleware stack.  When ``None`` (default), JWT auth is **skipped**
        (dev / unit-test mode — override via the environment variable
        ``CONTEXTIQ_JWT_AUTH_ENABLED``).
    """

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ANN001
        """Delegate startup/shutdown to the FastMCP SSE app's lifespan.

        Also seeds the circuit-breaker Prometheus gauge so the metric is
        available for scraping immediately on startup (TASK-US001-04).

        Initialises the OTel tracer provider and FastAPI auto-instrumentation
        (TASK-US001-05).

        Starts the Redis pub/sub cache-invalidation subscriber (TASK-US002-03).
        """
        # Initialise OTel — must run before yielding so spans are available
        # during request handling.  Failure is non-fatal (logged warning only).
        setup_telemetry(
            otel_endpoint=settings.otel_endpoint,
            sampler_arg=settings.otel_sampler_arg,
        )

        # Attach FastAPI auto-instrumentation (HTTP spans for every route).
        try:
            from opentelemetry import trace
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(
                app,
                tracer_provider=trace.get_tracer_provider(),
            )
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning(
                "FastAPIInstrumentor failed — HTTP spans will not be emitted.",
                exc_info=True,
            )

        # Ensure gauge reflects initial closed state on every (re)start.
        circuit_state_gauge.labels(name=gateway_breaker.name).set(0)

        # Start Redis pub/sub cache-invalidation subscriber (TASK-US002-03).
        # The Redis URL is read from the environment; if absent the subscriber
        # is skipped so the gateway can still start without Redis.
        _invalidation_task: asyncio.Task[Any] | None = None
        _redis_url = os.environ.get("CONTEXTIQ_REDIS_URL", "")
        if _redis_url:
            try:
                import redis.asyncio as aioredis  # noqa: PLC0415

                _redis_client = aioredis.from_url(_redis_url, decode_responses=True)
                _cache = ToolListCache(_redis_client)
                _invalidation_task = asyncio.create_task(
                    start_cache_invalidation_subscriber(_redis_client, _cache),
                    name="tool_cache_invalidation",
                )
                logger.info("Cache invalidation subscriber task started")
            except Exception:
                logger.warning(
                    "Could not start cache invalidation subscriber",
                    exc_info=True,
                )

        async with sse_app.lifespan(app):
            # Initialise ConnectorRegistry (TASK-US021-02).
            # Connectors that fail authenticate() are registered as disabled
            # so the gateway continues serving other connectors.
            _connector_registry = ConnectorRegistry()
            await _connector_registry.load()
            app.state.connector_registry = _connector_registry
            _health_poller = ConnectorHealthPoller(registry=_connector_registry)
            _health_poller.start()
            app.state.connector_health_poller = _health_poller
            yield
            _health_poller.stop()

        if _invalidation_task is not None and not _invalidation_task.done():
            _invalidation_task.cancel()
            try:
                await _invalidation_task
            except asyncio.CancelledError:
                pass
            logger.info("Cache invalidation subscriber task stopped")

    gateway = FastAPI(
        title="ContextIQ MCP Gateway",
        version=settings.server_version,
        lifespan=_lifespan,
    )

    # ------------------------------------------------------------------
    # Outermost catch-all error handler (TASK-US003-03)
    # Must be added first so it wraps all other middleware and handlers.
    # ------------------------------------------------------------------
    gateway.add_middleware(ErrorHandlerMiddleware)

    # ------------------------------------------------------------------
    # Circuit-breaker middleware (TASK-US001-04)
    # Must be added before routes so it wraps the entire request chain.
    # ------------------------------------------------------------------
    gateway.add_middleware(CircuitBreakerMiddleware)

    # ------------------------------------------------------------------
    # Connection tracing middleware (TASK-US001-05)
    # Added after CircuitBreakerMiddleware so only admitted connections
    # produce spans.
    # ------------------------------------------------------------------
    gateway.add_middleware(ConnectionTracingMiddleware)

    # ------------------------------------------------------------------
    # Request context middleware (TASK-US003-04)
    # Stamps each request with a fresh RequestContext (request_id, user_id,
    # session_id, trace_id) so concurrent tool calls are fully isolated.
    # Must run after ConnectionTracingMiddleware so the OTel span exists.
    # ------------------------------------------------------------------
    gateway.add_middleware(RequestContextMiddleware)

    # ------------------------------------------------------------------
    # JWT authentication middleware (TASK-US004-01)
    # Must be added LAST so FastAPI inserts it outermost — every request
    # hits JWT auth before any inner middleware or handler executes.
    # Skip registration when no jwks_client is provided (dev/test mode).
    # ------------------------------------------------------------------
    if jwks_client is not None:
        gateway.add_middleware(JWTAuthMiddleware, jwks_client=jwks_client)

    # ------------------------------------------------------------------
    # SSE transport
    # ------------------------------------------------------------------
    gateway.mount(f"{settings.mcp_path}/sse", sse_app)

    # ------------------------------------------------------------------
    # WebSocket transport
    # ------------------------------------------------------------------
    @gateway.websocket(f"{settings.mcp_path}/ws")
    async def mcp_ws_endpoint(websocket: WebSocket) -> None:
        """
        WebSocket MCP transport endpoint.

        Bridges the WebSocket connection to the FastMCP server using
        ``anyio`` in-memory streams so the MCP protocol runs unchanged
        regardless of the underlying network transport.
        """
        await websocket.accept()

        # Typed annotations for mypy; runtime values are untyped streams.
        c2s_send: MemoryObjectSendStream[Any]
        c2s_recv: MemoryObjectReceiveStream[Any]
        s2c_send: MemoryObjectSendStream[Any]
        s2c_recv: MemoryObjectReceiveStream[Any]

        c2s_send, c2s_recv = anyio.create_memory_object_stream(max_buffer_size=32)
        s2c_send, s2c_recv = anyio.create_memory_object_stream(max_buffer_size=32)

        async def _ws_reader() -> None:
            """Forward inbound WebSocket frames → MCP server read stream."""
            try:
                async for text in websocket.iter_text():
                    if _msg_ta is not None and _SessionMessage is not None:
                        json_msg = _msg_ta.validate_json(text)
                        session_msg = _SessionMessage(message=json_msg)
                    else:
                        import json  # noqa: PLC0415

                        session_msg = json.loads(text)
                    await c2s_send.send(session_msg)
            except WebSocketDisconnect:
                pass
            finally:
                await c2s_send.aclose()

        async def _ws_writer() -> None:
            """Forward MCP server write stream → outbound WebSocket frames."""
            async for item in s2c_recv:
                if isinstance(item, Exception):
                    break
                if _msg_ta is not None and _SessionMessage is not None:
                    # item is SessionMessage; serialize the inner JSONRPCMessage
                    inner = item.message if hasattr(item, "message") else item
                    payload = _msg_ta.dump_json(inner, exclude_none=True).decode()
                else:
                    import json  # noqa: PLC0415

                    payload = json.dumps(item)
                await websocket.send_text(payload)

        async with anyio.create_task_group() as tg:
            tg.start_soon(_ws_reader)
            tg.start_soon(_ws_writer)
            tg.start_soon(
                mcp._mcp_server.run,
                c2s_recv,
                s2c_send,
                mcp._mcp_server.create_initialization_options(),
            )

    # ------------------------------------------------------------------
    # Health probe
    # ------------------------------------------------------------------
    @gateway.get("/healthz")
    async def healthz() -> dict[str, object]:
        """Liveness / readiness probe — no authentication required."""
        return {"status": "ok", "transport": ["sse", "websocket"]}

    return gateway


# Production ASGI singleton — consumed by uvicorn.
app: FastAPI = create_gateway_app()
