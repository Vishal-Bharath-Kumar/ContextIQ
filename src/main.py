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
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from src.api.admin.routes.audit_log import router as audit_log_router
from src.api.admin.routes.governance import router as governance_router
from src.api.admin.routes.policies import router as policies_router
from src.api.admin.routes.replay import router as replay_router
from src.auth.dev_login import router as dev_login_router
from src.auth.jwks_client import JWKSClient
from src.auth.keycloak_settings import KeycloakSettings
from src.auth.middleware import JWTAuthMiddleware
from src.auth.oauth_metadata import (
    MCP_REQUIRED_SCOPES,
    PROTECTED_RESOURCE_METADATA_PATH,
    build_protected_resource_metadata,
)
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

    @new_app.get("/", response_class=HTMLResponse)
    async def root(request: Request) -> str:
        """Human-facing landing page for the local API/MCP service."""
        keycloak_settings = KeycloakSettings()
        mcp_url = f"{request.base_url}mcp/"
        metadata_url = f"{request.base_url}.well-known/oauth-protected-resource"
        auth_server = keycloak_settings.public_issuer
        return f"""
<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"utf-8\">
        <title>ContextIQ Local API</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 40px; line-height: 1.5; color: #1f2937; }}
            code {{ background: #f3f4f6; padding: 0.15rem 0.35rem; border-radius: 4px; }}
            a {{ color: #2563eb; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .panel {{ max-width: 760px; padding: 24px; border: 1px solid #e5e7eb; border-radius: 12px; background: #ffffff; }}
        </style>
    </head>
    <body>
        <div class=\"panel\">
            <h1>ContextIQ Local API</h1>
            <p><code>{request.base_url}</code> is the protected API and MCP resource server, not the browser login page.</p>
            <p>For MCP authentication, VS Code should call <code>{mcp_url}</code>, receive an OAuth challenge, read <code>{metadata_url}</code>, and then open the Keycloak authorization flow.</p>
            <p>Authorization server: <a href=\"{auth_server}\">{auth_server}</a></p>
            <p>If VS Code still opens this page or shows a client-ID prompt, reload the window and restart the ContextIQ MCP server so it picks up the current <code>oauth.clientId</code> workspace configuration.</p>
        </div>
    </body>
</html>
"""

    @new_app.get("/.well-known/oauth-authorization-server")
    async def oauth_authorization_server_metadata(request: Request) -> dict[str, object]:
        """Expose OAuth authorization-server metadata on the MCP origin."""
        origin = str(request.base_url).rstrip("/")
        keycloak_settings = KeycloakSettings()
        async with httpx.AsyncClient(timeout=10.0) as client:
            upstream = await client.get(keycloak_settings.internal_openid_configuration_uri)
            upstream.raise_for_status()
        metadata = upstream.json()
        metadata["authorization_endpoint"] = f"{origin}/authorize"
        metadata["token_endpoint"] = f"{origin}/token"
        metadata["revocation_endpoint"] = f"{origin}/revoke"
        metadata["issuer"] = keycloak_settings.public_issuer
        metadata["scopes_supported"] = list(MCP_REQUIRED_SCOPES)
        return metadata

    @new_app.get("/.well-known/openid-configuration")
    async def openid_configuration(request: Request) -> dict[str, object]:
        """OIDC discovery alias for clients that probe this path on the MCP origin."""
        return await oauth_authorization_server_metadata(request)

    @new_app.get("/authorize")
    async def authorize(request: Request) -> RedirectResponse:
        """Redirect same-origin OAuth authorization requests to Keycloak."""
        keycloak_settings = KeycloakSettings()
        query = urlencode(list(request.query_params.multi_items()))
        target = keycloak_settings.authorization_endpoint
        if query:
            target = f"{target}?{query}"
        return RedirectResponse(url=target, status_code=307)

    @new_app.post("/token")
    async def token(request: Request) -> Response:
        """Proxy token exchange requests from same-origin OAuth clients to Keycloak."""
        keycloak_settings = KeycloakSettings()
        body = await request.body()
        async with httpx.AsyncClient(timeout=15.0) as client:
            upstream = await client.post(
                keycloak_settings.token_uri,
                content=body,
                headers={"Content-Type": request.headers.get("content-type", "application/x-www-form-urlencoded")},
            )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    @new_app.post("/revoke")
    async def revoke(request: Request) -> Response:
        """Proxy token revocation requests from same-origin OAuth clients to Keycloak."""
        keycloak_settings = KeycloakSettings()
        body = await request.body()
        async with httpx.AsyncClient(timeout=15.0) as client:
            upstream = await client.post(
                keycloak_settings.revocation_endpoint,
                content=body,
                headers={"Content-Type": request.headers.get("content-type", "application/x-www-form-urlencoded")},
            )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    @new_app.get(PROTECTED_RESOURCE_METADATA_PATH)
    async def oauth_protected_resource_metadata(request: Request) -> dict[str, object]:
        """Advertise OAuth metadata so MCP clients can trigger browser login."""
        origin = str(request.base_url).rstrip("/")
        return build_protected_resource_metadata(origin, gateway_settings.mcp_path)

    return new_app


# Production singleton — consumed by uvicorn (e.g. `uvicorn src.main:app`).
app = create_app()
