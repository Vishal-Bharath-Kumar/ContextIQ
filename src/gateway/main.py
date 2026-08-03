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
from typing import TYPE_CHECKING, Any

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter

from src.connector_sdk.health_poller import ConnectorHealthPoller
from src.connector_sdk.registry import ConnectorRegistry
from src.data.database import primary_session_factory
from src.data.redis_client import create_redis_client
from src.gateway.config import settings
from src.gateway.handlers.tools_call import (
    set_builtin_tool_trace_object_store,
    set_builtin_tool_trace_session_factory,
)
from src.gateway.lifespan import start_cache_invalidation_subscriber, start_entity_consumer, start_indexing_consumer
from src.gateway.mcp_server import mcp, sse_app
from src.gateway.middleware.circuit_breaker import CircuitBreakerMiddleware
from src.gateway.middleware.context_middleware import RequestContextMiddleware
from src.gateway.middleware.error_handler import ErrorHandlerMiddleware
from src.gateway.middleware.jwt_auth import JWTAuthMiddleware
from src.gateway.middleware.tracing import ConnectionTracingMiddleware
from src.gateway.state import circuit_state_gauge, gateway_breaker
from src.gateway.telemetry import setup_telemetry
from src.governance.opa.bundle_loader import BundleNotReadyError, PolicyBundleLoader
from src.governance.opa.client import OPAClient
from src.governance.opa.health import default_opa_health_status, opa_health_status
from src.governance.nodes.opa_filter_node import set_opa_client
from src.knowledge_graph.extraction.extractor import ExtractionSettings
from src.knowledge_graph.inference.edge_inference_engine import EdgeInferenceSettings
from src.knowledge_graph.traversal.entity_linker import EntityLinkerSettings
from src.llm.ollama_verify import default_ollama_verification_status, verify_ollama_models_available
from src.registry.cache.tool_cache import ToolListCache
from src.agents.checkpointer import get_redis_checkpointer
from src.agents.config import settings as agent_settings
from src.agents.graph import build_graph
from src.agents.nodes.retrieval import set_connector_registry
from src.audit.trace.object_store import TraceObjectStore
from src.audit.trace.writer_node import set_trace_object_store, set_trace_session_factory
from src.gateway.tools.clarification_reply import set_graph as set_clarification_graph
from src.model_router.runtime_services import RoutingRuntimeServices
from src.observability.langfuse_integration import get_langfuse

if TYPE_CHECKING:
    from src.indexing.consumer import IndexingConsumer

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
            app.state.ollama_verification = await verify_ollama_models_available(
                [
                    agent_settings.llm_model_id,
                    EntityLinkerSettings().model_id,
                    ExtractionSettings().model_id,
                    EdgeInferenceSettings().model_id,
                ]
            )
            app.state.opa_health = default_opa_health_status()

            # Initialise ConnectorRegistry (TASK-US021-02).
            # Connectors that fail authenticate() are registered as disabled
            # so the gateway continues serving other connectors.
            _connector_registry = ConnectorRegistry()
            await _connector_registry.load()
            app.state.connector_registry = _connector_registry
            set_connector_registry(_connector_registry)
            _health_poller = ConnectorHealthPoller(registry=_connector_registry)
            _health_poller.start()
            app.state.connector_health_poller = _health_poller

            try:
                trace_store = TraceObjectStore()
                set_trace_object_store(trace_store)
                set_trace_session_factory(primary_session_factory())
                set_builtin_tool_trace_object_store(trace_store)
                set_builtin_tool_trace_session_factory(primary_session_factory())
                app.state.trace_object_store = trace_store
            except Exception:
                logger.warning("Could not configure trace writer dependencies", exc_info=True)

            routing_runtime = RoutingRuntimeServices(
                redis=create_redis_client(),
                session_factory=primary_session_factory(),
                langfuse=get_langfuse(),
            )
            app.state.routing_runtime = routing_runtime

            _graph_checkpointer = None
            try:
                _graph_checkpointer = await get_redis_checkpointer()
                graph = build_graph(
                    checkpointer=_graph_checkpointer,
                    runtime_config={"routing_runtime": routing_runtime},
                )
                set_clarification_graph(graph)
                app.state.agent_graph = graph
                app.state.agent_graph_checkpointer = _graph_checkpointer
            except Exception:
                logger.warning("Could not initialise gateway agent graph", exc_info=True)

            # Start indexing consumer (TASK-US027-04).
            # Guarded by DATABASE_URL so the gateway can start in dev/test
            # environments without all stores configured.
            _consumer_task: asyncio.Task[Any] | None = None
            _indexing_consumer = None
            if os.environ.get("DATABASE_URL"):
                try:
                    _indexing_consumer = _build_indexing_consumer(_connector_registry)
                    _consumer_task = asyncio.create_task(
                        start_indexing_consumer(_indexing_consumer),
                        name="indexing_consumer",
                    )
                    app.state.indexing_consumer = _indexing_consumer
                    logger.info("Indexing consumer task started")
                except Exception:
                    logger.warning(
                        "Could not start indexing consumer",
                        exc_info=True,
                    )

            # Initialise OPA client and verify bundle (TASK-US032-02).
            # Guarded by OPA_BASE_URL so the gateway can start without an OPA
            # sidecar in dev/test environments.
            opa_base_url = os.environ.get("OPA_BASE_URL")
            if opa_base_url:
                _bundle_loader = PolicyBundleLoader()
                try:
                    app.state.bundle_info = await _bundle_loader.verify()
                    app.state.opa_client = OPAClient()
                    set_opa_client(app.state.opa_client)
                    app.state.opa_health = opa_health_status(
                        configured=True,
                        bundle_ready=True,
                        degraded=False,
                        bundle_version=app.state.bundle_info.version,
                    )
                    logger.info(
                        "OPA client ready — bundle version=%s",
                        app.state.bundle_info.version,
                    )
                except BundleNotReadyError:
                    app.state.opa_health = opa_health_status(
                        configured=True,
                        bundle_ready=False,
                        degraded=False,
                        error="OPA bundle not ready",
                    )
                    logger.critical("OPA bundle not ready — refusing to start")
                    raise

            # Start entity consumer (TASK-US028-04).
            # Guarded by NEO4J_URI so the gateway can start without Neo4j
            # configured in dev/test environments.
            _entity_consumer_task: asyncio.Task[Any] | None = None
            _entity_consumer = None
            if os.environ.get("NEO4J_URI"):
                try:
                    from src.knowledge_graph.consumer import EntityConsumer  # noqa: PLC0415
                    from src.knowledge_graph.extraction.extractor import EntityExtractor  # noqa: PLC0415

                    _entity_consumer = EntityConsumer(
                        extractor=EntityExtractor(),
                        neo4j_store=app.state.neo4j_store,
                    )
                    _entity_consumer_task = asyncio.create_task(
                        start_entity_consumer(_entity_consumer),
                        name="entity_consumer",
                    )
                    app.state.entity_consumer = _entity_consumer
                    logger.info("Entity consumer task started")
                except Exception:
                    logger.warning(
                        "Could not start entity consumer",
                        exc_info=True,
                    )

            yield

            await routing_runtime.close()

            if _graph_checkpointer is not None:
                await _graph_checkpointer.aclose()

            if _indexing_consumer is not None:
                await _indexing_consumer.stop()
            if _consumer_task is not None and not _consumer_task.done():
                _consumer_task.cancel()
                try:
                    await _consumer_task
                except asyncio.CancelledError:
                    pass
                logger.info("Indexing consumer task stopped")

            if _entity_consumer is not None:
                await _entity_consumer.stop()
            if _entity_consumer_task is not None and not _entity_consumer_task.done():
                _entity_consumer_task.cancel()
                try:
                    await _entity_consumer_task
                except asyncio.CancelledError:
                    pass
                logger.info("Entity consumer task stopped")

            _health_poller.stop()

            if hasattr(app.state, "opa_client"):
                await app.state.opa_client.close()
                logger.info("OPA client closed")

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
        return {
            "status": "ok",
            "transport": ["sse", "websocket"],
            "ollama": getattr(gateway.state, "ollama_verification", default_ollama_verification_status()),
            "opa": getattr(gateway.state, "opa_health", default_opa_health_status()),
        }

    return gateway


def _build_indexing_consumer(connector_registry: ConnectorRegistry) -> IndexingConsumer:
    """Construct an ``IndexingConsumer`` with all required dependencies.

    Dependencies that have their own ``*Settings`` classes are instantiated
    using environment variables so no explicit configuration is needed here.
    A fresh ``AsyncSession`` is created from the primary session factory
    for the lifetime of the consumer background task.
    """
    from src.data.database import primary_session_factory  # noqa: PLC0415
    from src.indexing.consumer import IndexingConsumer  # noqa: PLC0415
    from src.indexing.embedding.service import EmbeddingService  # noqa: PLC0415
    from src.indexing.pipeline import IndexingPipeline  # noqa: PLC0415
    from src.indexing.repositories.chunk_repository import ChunkRepository  # noqa: PLC0415
    from src.indexing.stores.deletion_handler import DeletionHandler  # noqa: PLC0415
    from src.indexing.stores.opensearch_indexer import OpenSearchIndexer  # noqa: PLC0415
    from src.indexing.stores.qdrant_indexer import QdrantIndexer  # noqa: PLC0415

    session = primary_session_factory()()
    chunk_repo = ChunkRepository(session)
    qdrant = QdrantIndexer()
    opensearch = OpenSearchIndexer()
    embedder = EmbeddingService()

    pipeline = IndexingPipeline(
        embedder=embedder,
        qdrant=qdrant,
        opensearch=opensearch,
        chunk_repo=chunk_repo,
        registry=connector_registry,
        # Enables lazily building a per-knowledge-source connector (from the
        # knowledge_sources table) the first time a source is synced, since
        # connector_registry only holds one shared, unscoped instance per
        # connector TYPE (entry-point discovery), not per source.
        session_factory=primary_session_factory(),
    )
    deletion_handler = DeletionHandler(
        chunk_repo=chunk_repo,
        qdrant=qdrant,
        opensearch=opensearch,
    )
    return IndexingConsumer(pipeline=pipeline, deletion_handler=deletion_handler)


# Production ASGI singleton — consumed by uvicorn.
app: FastAPI = create_gateway_app()
