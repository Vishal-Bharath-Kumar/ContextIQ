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

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.admin.routes.audit_log import router as audit_log_router
from src.api.admin.routes.model_analytics import router as model_analytics_router
from src.api.admin.routes.policies import router as policies_router
from src.api.admin.routes.replay import router as replay_router
from src.auth.jwks_client import JWKSClient
from src.auth.keycloak_settings import KeycloakSettings
from src.auth.middleware import JWTAuthMiddleware
from src.gateway.mcp_handler import mcp_router
from src.knowledge_sources.routers.knowledge_source_router import router as knowledge_sources_router
from src.model_registry.routers.model_router import router as model_router
from src.model_router.routers.routing_weight_router import router as routing_weight_router
from src.observability.cost.settings import LangfuseProjectSettings
from src.observability.metrics.middleware import MetricsMiddleware
from src.observability.metrics.router import metrics_router
from src.observability.metrics.settings import MetricsSettings
from src.observability.tracing.setup import setup_tracing, teardown_tracing
from src.registry.routers.tool_router import router as tool_registry_router

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
        setup_tracing()  # AC-7: called once at startup
        if manage_lifecycle:
            await client.startup()
        app.state.jwks_client = client
        _langfuse_settings = LangfuseProjectSettings()
        logger.info(
            "Langfuse cost recording enabled. "
            "Ensure project data retention >= %d months (AC-5).",
            _langfuse_settings.required_retention_months,
        )
        yield
        if manage_lifecycle:
            await client.shutdown()
        teardown_tracing()  # flush spans before shutdown

    new_app = FastAPI(title="ContextIQ", version="0.1.0", lifespan=_lifespan)

    # Metrics middleware — mount BEFORE JWT so instrumentation wraps all request handling
    new_app.add_middleware(MetricsMiddleware, settings=MetricsSettings())

    # JWT middleware — wraps all routes; pre-started client passed directly.
    new_app.add_middleware(JWTAuthMiddleware, jwks_client=client)

    # Protected routers — RBAC guards applied at router level (TASK-US042-03)
    new_app.include_router(mcp_router)
    new_app.include_router(knowledge_sources_router)
    new_app.include_router(model_router)
    new_app.include_router(routing_weight_router)
    new_app.include_router(policies_router)
    new_app.include_router(replay_router)
    new_app.include_router(model_analytics_router)
    new_app.include_router(metrics_router)
    new_app.include_router(audit_log_router)
    new_app.include_router(tool_registry_router)

    @new_app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness/readiness probe — no authentication required (_SKIP_PATHS)."""
        return {"status": "ok"}

    return new_app


# Production singleton — consumed by uvicorn (e.g. `uvicorn src.main:app`).
app = create_app()
