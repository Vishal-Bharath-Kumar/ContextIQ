"""
Core RBAC FastAPI dependency for ContextIQ.

Provides decode_jwt_claims — a FastAPI Depends() dependency that retrieves
the JWTClaims object already set on request.state by JWTAuthMiddleware
(TASK-US004-01).  No second JWT decode is performed per request (AC-4).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from src.gateway.schemas.auth_types import JWTClaims


def _get_verified_claims(request: Request) -> JWTClaims:
    """
    Extract JWTClaims from ASGI scope state populated by JWTAuthMiddleware.

    The middleware verifies the token signature and expiry before storing the
    claims, so this dependency trusts whatever is in request.state.jwt_claims
    without re-decoding.

    Raises HTTP 401 if claims are absent (middleware was bypassed, e.g. in
    unit tests that do not configure the middleware).
    """
    claims: JWTClaims | None = getattr(request.state, "jwt_claims", None)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


# Public name — route handlers reference this as Depends(decode_jwt_claims)
decode_jwt_claims = _get_verified_claims

# Annotated type alias for clean dependency injection in route signatures:
#   async def my_route(claims: JWTClaimsDep) -> ...:
JWTClaimsDep = Annotated[JWTClaims, Depends(decode_jwt_claims)]
