"""
Admin portal dependency shim — backwards-compatible wrapper.

The original ad-hoc require_admin_role implementation is replaced by a thin
delegate to the canonical RBAC system (src.auth.dependencies + src.auth.roles).
Existing route handlers that import require_admin_role from this module
continue to work without changes.

New code should use require_roles(PlatformRole.ADMIN) from src.auth.rbac
(TASK-US042-02) instead of this shim.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status

from src.auth.dependencies import decode_jwt_claims
from src.auth.roles import PlatformRole
from src.gateway.schemas.auth_types import JWTClaims


def require_admin_role(
    claims: Annotated[JWTClaims, Depends(decode_jwt_claims)],
) -> JWTClaims:
    """
    Backwards-compatible admin gate.

    Delegates role verification to JWTClaims.has_role() which uses the
    canonical ROLE_PERMISSION_MATRIX and case-insensitive matching (AC-4).
    Raises HTTP 403 if the token does not carry the ADMIN role.
    """
    if not claims.has_role(PlatformRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
    return claims
