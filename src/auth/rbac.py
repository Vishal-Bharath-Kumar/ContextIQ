"""
RBAC enforcement layer for ContextIQ — TASK-US042-02.

Provides two factory functions:
- require_permission(permission) — matrix-driven check (reads ROLE_PERMISSION_MATRIX)
- require_roles(*roles)          — direct role-set check (logical OR, ADMIN always passes)

Both return FastAPI dependency callables that resolve to verified JWTClaims on
success or raise HTTP 403 on denial.  Pre-built named callables at module level
are the canonical injection points for all route files.

Every denial emits a structured WARNING log for security audit trails (AC-6).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, status

from src.auth.dependencies import JWTClaimsDep
from src.auth.roles import ROLE_PERMISSION_MATRIX, Permission, PlatformRole
from src.gateway.schemas.auth_types import JWTClaims

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def require_permission(permission: Permission) -> Callable[..., Awaitable[JWTClaims]]:
    """
    Factory: returns a FastAPI dependency that enforces the given Permission.

    Reads ROLE_PERMISSION_MATRIX — the single source of truth (AC-2). ADMIN
    is a super-role: any token carrying ADMIN passes regardless of which
    permission is checked.

    Usage::

        # As a route dependency (no claims needed in handler)
        @router.get(
            "/v1/traces",
            dependencies=[Depends(require_permission(Permission.READ_TRACES))],
        )
        async def list_traces() -> ...: ...

        # As a typed parameter (claims available in handler)
        @router.get("/v1/traces")
        async def list_traces(
            claims: JWTClaims = Depends(require_permission(Permission.READ_TRACES)),
        ) -> ...: ...
    """

    async def _check(claims: JWTClaimsDep) -> JWTClaims:
        if not claims.has_permission(permission):
            _log_denial(claims, permission=permission)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission}",
            )
        return claims

    # Readable name in OpenAPI security scheme descriptions and test output.
    _check.__name__ = f"require_{permission}"
    return _check


def require_roles(*roles: PlatformRole) -> Callable[..., Awaitable[JWTClaims]]:
    """
    Factory: returns a FastAPI dependency that passes when the JWT contains ANY
    of the specified roles (logical OR).

    ADMIN is an implicit super-role: any token carrying ADMIN passes even when
    ADMIN is not listed in ``roles``.  This ensures that administrative users
    are never accidentally locked out by a missing role in the call site.

    Usage::

        dependencies=[Depends(require_roles(PlatformRole.AUDITOR, PlatformRole.DEVOPS_SRE))]
    """
    role_set = frozenset(roles)

    async def _check(claims: JWTClaimsDep) -> JWTClaims:
        if not (claims.has_role(PlatformRole.ADMIN) or claims.has_any_role(*role_set)):
            _log_denial(claims, roles=role_set)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"One of the following roles required: "
                    f"{', '.join(r.value for r in roles)}"
                ),
            )
        return claims

    _check.__name__ = f"require_roles({'|'.join(r.value for r in roles)})"
    return _check


def _log_denial(
    claims: JWTClaims,
    *,
    permission: Permission | None = None,
    roles: frozenset[PlatformRole] | None = None,
) -> None:
    """
    Emit a structured WARNING for every HTTP 403 denial (AC-6 — audit log).

    Fields logged:
    - user          : JWT subject (user ID)
    - user_roles    : sorted list of roles from the token
    - required_permission : the Permission atom checked (or None)
    - required_roles      : sorted list of roles required (or None)
    """
    logger.warning(
        "RBAC denial: user=%s user_roles=%s required_permission=%s required_roles=%s",
        claims.sub,
        sorted(claims.roles),
        permission,
        sorted(r.value for r in roles) if roles else None,
    )


# ---------------------------------------------------------------------------
# Named dependency callables — canonical injection points for route files.
#
# Using named callables (not lambdas) produces readable OpenAPI security
# scheme descriptions and clearer test assertion output (AC-3).
#
# Role-based callables (require_roles): pass on any listed role or ADMIN.
# Permission-based callables (require_permission): pass when
#     ROLE_PERMISSION_MATRIX[permission] contains the token's role.
# ---------------------------------------------------------------------------

# Role-based — pre-approved role sets matching AC-1 role definitions
require_developer = require_roles(
    PlatformRole.DEVELOPER,
    PlatformRole.PLATFORM_ENGINEER,
    PlatformRole.ADMIN,
)

require_platform_engineer = require_roles(
    PlatformRole.PLATFORM_ENGINEER,
    PlatformRole.ADMIN,
)

require_security_officer = require_roles(
    PlatformRole.SECURITY_OFFICER,
    PlatformRole.ADMIN,
)

require_auditor = require_roles(
    PlatformRole.AUDITOR,
    PlatformRole.DEVOPS_SRE,
    PlatformRole.SECURITY_OFFICER,
    PlatformRole.ADMIN,
)

require_manager = require_roles(
    PlatformRole.MANAGER,
    PlatformRole.PLATFORM_ENGINEER,
    PlatformRole.ADMIN,
)

require_admin = require_roles(PlatformRole.ADMIN)

require_devops = require_roles(
    PlatformRole.DEVOPS_SRE,
    PlatformRole.PLATFORM_ENGINEER,
    PlatformRole.ADMIN,
)

# Permission-atom equivalents — preferred for new code (matrix-driven AC-2)
require_context_tools     = require_permission(Permission.CALL_CONTEXT_TOOLS)
require_manage_connectors = require_permission(Permission.MANAGE_CONNECTORS)
require_manage_models     = require_permission(Permission.MANAGE_MODELS)
require_manage_policies   = require_permission(Permission.MANAGE_POLICIES)
require_read_traces       = require_permission(Permission.READ_TRACES)
require_read_metrics      = require_permission(Permission.READ_METRICS)
require_cost_analytics    = require_permission(Permission.READ_COST_ANALYTICS)
