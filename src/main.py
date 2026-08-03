"""
ContextIQ FastAPI application entry point.

Mounts all protected routers (EP-014 RBAC guards applied at router level —
TASK-US042-03) and the public /healthz endpoint.

TASK-US043-03: Adds JWTAuthMiddleware (Keycloak JWKS validation) and a
lifespan context manager that starts/stops the shared JWKSClient.

TASK-US043-05: `create_app()` factory allows tests to inject a pre-warmed
JWKSClient backed by a respx mock without touching the module-level client.
"""
from __future__ import annotations

from contextlib import AsyncExitStack
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.admin.routes.audit_log import router as audit_log_router
from src.api.admin.routes.governance import router as governance_router
from src.api.admin.routes.policies import router as policies_router
from src.api.admin.routes.replay import router as replay_router
from src.auth.dev_login import router as dev_login_router
from src.auth.jwks_client import JWKSClient
from src.auth.keycloak_settings import KeycloakSettings
from src.auth.middleware import JWTAuthMiddleware
from src.agents.checkpointer import get_redis_checkpointer
from src.connector_sdk.registry import ConnectorRegistry
from src.data.database import primary_session_factory
from src.data.redis_client import create_redis_client
from src.agents.graph import build_graph
from src.agents.nodes.retrieval import set_connector_registry
from src.audit.trace.object_store import TraceObjectStore
from src.audit.trace.writer_node import set_trace_object_store, set_trace_session_factory
from src.gateway.config import settings as gateway_settings
from src.gateway.middleware.context_middleware import RequestContextMiddleware
from src.gateway.mcp_handler import mcp_router
from src.gateway.mcp_server import sse_app, streamable_http_app
from src.gateway.tools.clarification_reply import set_graph as set_clarification_graph
from src.governance.nodes.opa_filter_node import set_opa_client
from src.governance.opa.bundle_loader import BundleNotReadyError, PolicyBundleLoader
from src.governance.opa.client import OPAClient
from src.knowledge_sources.routers.knowledge_source_router import router as knowledge_sources_router
from src.knowledge_sources.runtime_connectors import apply_runtime_connector_overrides
from src.knowledge_sources.sync.scheduler import CronSyncScheduler
from src.model_registry.routers.model_router import router as model_router
from src.model_router.routers.routing_weight_router import router as routing_weight_router
from src.model_router.runtime_services import RoutingRuntimeServices
from src.observability.langfuse_integration import get_langfuse, setup_langfuse, teardown_langfuse
from src.observability.langfuse_integration.settings import LangfuseSettings
from src.observability.metrics.middleware import MetricsMiddleware
from src.observability.metrics.router import metrics_router
from src.observability.metrics.settings import MetricsSettings
from src.observability.tracing.setup import setup_tracing, teardown_tracing
from src.registry.routers.tool_router import router as tool_registry_router
from src.agents.config import settings as agent_settings
from src.governance.opa.health import default_opa_health_status, opa_health_status
from src.knowledge_graph.extraction.extractor import ExtractionSettings
from src.knowledge_graph.inference.edge_inference_engine import EdgeInferenceSettings
from src.knowledge_graph.traversal.entity_linker import EntityLinkerSettings
from src.llm.ollama_verify import default_ollama_verification_status, verify_ollama_models_available

logger = logging.getLogger(__name__)

# Module-level default client — used by the production `app` singleton.
# Tests pass a pre-started client to `create_app()` instead of using this.
_jwks_client = JWKSClient(KeycloakSettings())


def create_app(jwks_client: JWKSClient | None = None) -> FastAPI:
    """
    FastAPI application factory.

    Parameters
    ----------
    jwks_client:
        When provided (e.g. in tests), the caller is responsible for calling
        ``startup()``/``shutdown()`` on the client.  The app lifespan will
        store the client on ``app.state`` but will NOT call startup/shutdown.
        When ``None`` (production), the module-level ``_jwks_client`` is used
        and its lifecycle is managed inside the lifespan context manager.
    """
    client: JWKSClient = jwks_client if jwks_client is not None else _jwks_client
    manage_lifecycle: bool = jwks_client is None

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Initialize observability stack
        setup_tracing()  # AC-7: OpenTelemetry tracing
        setup_langfuse()  # Langfuse LLM tracing

        async with AsyncExitStack() as stack:
            await stack.enter_async_context(sse_app.lifespan(app))
            await stack.enter_async_context(streamable_http_app.lifespan(app))
            if manage_lifecycle:
                await client.startup()
            app.state.jwks_client = client
            _langfuse_settings = LangfuseSettings()
            if _langfuse_settings.is_configured:
                logger.info(
                    "Langfuse observability enabled (environment: %s, base_url: %s)",
                    _langfuse_settings.environment,
                    _langfuse_settings.base_url,
                )

            app.state.ollama_verification = await verify_ollama_models_available(
                [
                    agent_settings.llm_model_id,
                    EntityLinkerSettings().model_id,
                    ExtractionSettings().model_id,
                    EdgeInferenceSettings().model_id,
                ]
            )
            app.state.opa_health = opa_health_status(
                configured=False,
                bundle_ready=False,
                degraded=False,
            )

            # Initialise ConnectorRegistry (TASK-US021-02) so the real GitHub/
            # Confluence/Jira/Grafana connectors are discovered and available to
            # the knowledge-sources sync endpoints/scheduler via app.state.
            # Connectors that fail authenticate() are registered as disabled so
            # the API continues serving the rest of the platform.
            connector_registry = ConnectorRegistry()
            await connector_registry.load()
            await apply_runtime_connector_overrides(
                connector_registry,
                primary_session_factory(),
            )
            app.state.connector_registry = connector_registry
            set_connector_registry(connector_registry)

            try:
                trace_store = TraceObjectStore()
                await trace_store.ensure_bucket_ready()
                set_trace_object_store(trace_store)
                set_trace_session_factory(primary_session_factory())
                app.state.trace_object_store = trace_store
            except Exception:
                logger.warning("Could not configure trace writer dependencies", exc_info=True)

            routing_runtime = RoutingRuntimeServices(
                redis=create_redis_client(),
                session_factory=primary_session_factory(),
                langfuse=get_langfuse(),
            )
            app.state.routing_runtime = routing_runtime

            graph_checkpointer = None
            try:
                graph_checkpointer = await get_redis_checkpointer()
            except Exception:
                logger.warning("Could not initialise MCP graph checkpointer", exc_info=True)

            try:
                graph = build_graph(
                    checkpointer=graph_checkpointer,
                    runtime_config={"routing_runtime": routing_runtime},
                )
                set_clarification_graph(graph)
                app.state.agent_graph = graph
                app.state.agent_graph_checkpointer = graph_checkpointer
            except Exception:
                logger.warning("Could not initialise MCP agent graph", exc_info=True)

            opa_base_url = os.environ.get("OPA_BASE_URL")
            if opa_base_url:
                bundle_loader = PolicyBundleLoader()
                try:
                    app.state.bundle_info = await bundle_loader.verify()
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
                except BundleNotReadyError as exc:
                    app.state.opa_client = OPAClient()
                    set_opa_client(app.state.opa_client)
                    app.state.opa_health = opa_health_status(
                        configured=True,
                        bundle_ready=False,
                        degraded=True,
                        error=str(exc),
                    )
                    logger.warning(
                        "OPA bundle not verified at startup; continuing with degraded policy health",
                        exc_info=True,
                    )

            scheduler = CronSyncScheduler(
                session_factory=primary_session_factory(),
                registry=connector_registry,
            )
            scheduler.start()
            app.state.sync_scheduler = scheduler

            yield

            # Cleanup observability stack
            scheduler.stop()
            await routing_runtime.close()
            if manage_lifecycle:
                await client.shutdown()
            teardown_langfuse()  # Flush Langfuse traces
            teardown_tracing()  # Flush OpenTelemetry spans

    new_app = FastAPI(title="ContextIQ", version="0.1.0", lifespan=_lifespan)

    # Metrics middleware — mount BEFORE JWT so instrumentation wraps all request handling
    new_app.add_middleware(MetricsMiddleware, settings=MetricsSettings())

    # RequestContext middleware — JWTAuthMiddleware must remain outermost so it
    # populates request.state before RequestContextMiddleware reads it.
    new_app.add_middleware(RequestContextMiddleware)

    # JWT middleware — wraps all routes; pre-started client passed directly.
    new_app.add_middleware(JWTAuthMiddleware, jwks_client=client)

    # Local-dev-only login route (returns 404 unless CONTEXTIQ_DEV_LOGIN_ENABLED=true).
    # Registered before the protected routers; its own path is in JWTAuthMiddleware's
    # _SKIP_PATHS since it's how a client obtains a token in the first place.
    new_app.include_router(dev_login_router)

    # Protected routers — RBAC guards applied at router level (TASK-US042-03)
    new_app.include_router(mcp_router)
    new_app.include_router(knowledge_sources_router)
    new_app.include_router(model_router)
    new_app.include_router(routing_weight_router)
    new_app.include_router(policies_router)
    new_app.include_router(governance_router)
    new_app.include_router(replay_router)
    new_app.include_router(metrics_router)
    new_app.include_router(audit_log_router)
    new_app.include_router(tool_registry_router)

    # FastMCP SSE transport for legacy IDE MCP clients.
    new_app.mount(f"{gateway_settings.mcp_path}/sse", sse_app)

    # FastMCP Streamable HTTP transport for modern MCP clients.
    new_app.mount(f"{gateway_settings.mcp_path}", streamable_http_app)

    @new_app.get("/healthz")
    async def healthz() -> dict[str, object]:
        """Liveness/readiness probe — no authentication required (_SKIP_PATHS)."""
        return {
            "status": "ok",
            "ollama": getattr(new_app.state, "ollama_verification", default_ollama_verification_status()),
            "opa": getattr(new_app.state, "opa_health", default_opa_health_status()),
        }

    return new_app


# Production singleton — consumed by uvicorn (e.g. `uvicorn src.main:app`).
app = create_app()
