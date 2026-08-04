"""
JWT authentication middleware for the ContextIQ MCP Gateway — TASK-US043-03.

Verifies every inbound request carries a valid Keycloak-issued JWT, stores the
decoded `JWTClaims` on `request.state.jwt_claims` so that RBAC dependencies
(TASK-US042-02) can consume them without re-verifying the token (AC-4).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi.responses import JSONResponse
from jose.exceptions import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.auth.jwks_client import JWKSClient
from src.auth.oauth_metadata import (
    PROTECTED_RESOURCE_METADATA_PATH,
    build_www_authenticate_header,
    is_mcp_path,
)
from src.gateway.config import settings as gateway_settings
from src.gateway.schemas.auth_types import JWTClaims

logger = logging.getLogger(__name__)

# Paths that bypass JWT validation entirely.
# These paths must be accessible without authentication:
#   /healthz      — Kubernetes liveness/readiness probe
#   /auth/health* — Keycloak management health (proxied internally)
#   /docs, /redoc, /openapi.json — FastAPI OpenAPI UI (dev only)
#   /metrics      — Prometheus scrape endpoint (secured by network policy)
_SKIP_PATHS: frozenset[str] = frozenset({
    "/",
    "/healthz",
    "/authorize",
    "/token",
    "/auth/health/ready",
    "/auth/health/live",
    "/auth/dev-login",  # local-dev-only login route (src/auth/dev_login.py); 404s unless enabled
    PROTECTED_RESOURCE_METADATA_PATH,
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
})
_INSERTED_PROTECTED_RESOURCE_METADATA_PATH = (
    f"{PROTECTED_RESOURCE_METADATA_PATH}{gateway_settings.mcp_path}"
)


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    AC-3: Validates Keycloak-issued JWTs on every inbound request.

    Flow:
      1. Skip validation for paths in `_SKIP_PATHS`.
      2. Require `Authorization: Bearer <token>` header.
      3. Verify token via `JWKSClient.decode()` (RS256 + iss + aud + exp).
      4. Store validated `JWTClaims` on `request.state.jwt_claims`.
      5. Return HTTP 401 for missing, malformed, or expired tokens (AC-6).
    """

    def __init__(self, app: Any, jwks_client: JWKSClient) -> None:
        super().__init__(app)
        self._jwks = jwks_client

    def _challenge_headers(
        self,
        request: Request,
        *,
        error: str | None = None,
        error_description: str | None = None,
    ) -> dict[str, str]:
        if not is_mcp_path(request.url.path, gateway_settings.mcp_path):
            return {}
        origin = str(request.base_url).rstrip("/")
        return {
            "WWW-Authenticate": build_www_authenticate_header(
                origin,
                error=error,
                error_description=error_description,
            )
        }

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.url.path in _SKIP_PATHS or request.url.path in {
            _INSERTED_PROTECTED_RESOURCE_METADATA_PATH,
            f"{_INSERTED_PROTECTED_RESOURCE_METADATA_PATH}/",
        }:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
                headers=self._challenge_headers(request),
            )

        token = auth_header.removeprefix("Bearer ").strip()

        try:
            raw_claims: dict[str, Any] = await self._jwks.decode(token)
        except JWTError as exc:
            logger.debug("JWT validation failed: %s", exc)
            return JSONResponse(
                status_code=401,
                content={"detail": "Token validation failed"},
                headers=self._challenge_headers(
                    request,
                    error="invalid_token",
                    error_description="Token validation failed",
                ),
            )

        try:
            claims = JWTClaims(**raw_claims)
        except Exception as exc:  # noqa: BLE001
            logger.warning("JWT claims schema mismatch: %s", exc)
            return JSONResponse(
                status_code=401,
                content={"detail": "Malformed JWT claims"},
                headers=self._challenge_headers(
                    request,
                    error="invalid_token",
                    error_description="Malformed JWT claims",
                ),
            )

        request.state.jwt_claims = claims
        request.state.user_id = claims.sub
        request.state.session_id = claims.jti or claims.sub
        return await call_next(request)
