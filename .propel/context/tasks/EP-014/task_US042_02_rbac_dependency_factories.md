# TASK-US042-02 — FastAPI RBAC Dependency Factories

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US042-02 |
| User Story | US-042 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the RBAC enforcement layer as FastAPI dependency factories (AC-3). `require_permission(permission)` is the generic factory that produces a `Depends`-compatible callable returning verified `JWTClaims` or raising HTTP 403. Pre-built named dependencies cover every permission atom defined in TASK-US042-01 and replace all ad-hoc role checks scattered across route files.

## Implementation Details

**Technology:** Python 3.11+, FastAPI `Depends`, Pydantic v2

**File locations:**
- `src/auth/rbac.py` — `require_permission()`, `require_roles()`, all named dependency callables
- `src/auth/__init__.py` — re-export public API

---

### `require_permission` and `require_roles` factories

```python
# src/auth/rbac.py
from __future__ import annotations
import logging
from typing     import Callable, Annotated
from fastapi    import Depends, HTTPException, status

from src.auth.dependencies          import JWTClaimsDep
from src.auth.roles                 import PlatformRole, Permission, ROLE_PERMISSION_MATRIX
from src.gateway.schemas.auth_types import JWTClaims

logger = logging.getLogger(__name__)


def require_permission(permission: Permission) -> Callable[..., JWTClaims]:
    """
    Factory: returns a FastAPI dependency that enforces the given Permission.
    Uses ROLE_PERMISSION_MATRIX — the single source of truth (AC-2).

    Usage:
        @router.get("/v1/traces", dependencies=[Depends(require_permission(Permission.READ_TRACES))])
        async def list_traces(...): ...

        # Or as a typed parameter:
        @router.get("/v1/traces")
        async def list_traces(claims: JWTClaims = Depends(require_permission(Permission.READ_TRACES))): ...
    """
    async def _check(claims: JWTClaimsDep) -> JWTClaims:
        if not claims.has_permission(permission):
            _log_denial(claims, permission=permission)
            raise HTTPException(
                status_code = status.HTTP_403_FORBIDDEN,
                detail      = f"Permission denied: {permission}",
            )
        return claims

    # Set a meaningful __name__ for OpenAPI and test introspection
    _check.__name__ = f"require_{permission}"
    return _check


def require_roles(*roles: PlatformRole) -> Callable[..., JWTClaims]:
    """
    Factory: returns a FastAPI dependency that passes when the JWT contains
    ANY of the specified roles (logical OR). ADMIN always passes.

    Usage:
        dependencies=[Depends(require_roles(PlatformRole.AUDITOR, PlatformRole.ADMIN))]
    """
    role_set = frozenset(roles)

    async def _check(claims: JWTClaimsDep) -> JWTClaims:
        if not (claims.has_role(PlatformRole.ADMIN) or claims.has_any_role(*role_set)):
            _log_denial(claims, roles=role_set)
            raise HTTPException(
                status_code = status.HTTP_403_FORBIDDEN,
                detail      = (
                    f"One of the following roles required: "
                    f"{', '.join(r.value for r in role_set)}"
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
    """Emit a structured warning for every 403 to support security audit logs."""
    logger.warning(
        "RBAC denial: user=%s user_roles=%s required_permission=%s required_roles=%s",
        claims.sub,
        sorted(claims.roles),
        permission,
        sorted(r.value for r in roles) if roles else None,
    )
```

---

### Named dependency callables

```python
# src/auth/rbac.py  (continued)
#
# These pre-built callables are the canonical injection points used throughout
# all route files. Using named callables (not lambdas) produces readable OpenAPI
# security scheme descriptions and clearer test assertion output.

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

# Permission-atom equivalents (preferred for new code — matrix-driven)
require_context_tools    = require_permission(Permission.CALL_CONTEXT_TOOLS)
require_manage_connectors = require_permission(Permission.MANAGE_CONNECTORS)
require_manage_models    = require_permission(Permission.MANAGE_MODELS)
require_manage_policies  = require_permission(Permission.MANAGE_POLICIES)
require_read_traces      = require_permission(Permission.READ_TRACES)
require_read_metrics     = require_permission(Permission.READ_METRICS)
require_cost_analytics   = require_permission(Permission.READ_COST_ANALYTICS)
```

---

### `src/auth/__init__.py` — public API re-exports

```python
# src/auth/__init__.py
from src.auth.roles        import PlatformRole, Permission, ROLE_PERMISSION_MATRIX, roles_for
from src.auth.dependencies import decode_jwt_claims, JWTClaimsDep
from src.auth.rbac         import (
    require_permission,
    require_roles,
    require_developer,
    require_platform_engineer,
    require_security_officer,
    require_auditor,
    require_manager,
    require_admin,
    require_devops,
    require_context_tools,
    require_manage_connectors,
    require_manage_models,
    require_manage_policies,
    require_read_traces,
    require_read_metrics,
    require_cost_analytics,
)

__all__ = [
    "PlatformRole", "Permission", "ROLE_PERMISSION_MATRIX", "roles_for",
    "decode_jwt_claims", "JWTClaimsDep",
    "require_permission", "require_roles",
    "require_developer", "require_platform_engineer", "require_security_officer",
    "require_auditor", "require_manager", "require_admin", "require_devops",
    "require_context_tools", "require_manage_connectors", "require_manage_models",
    "require_manage_policies", "require_read_traces", "require_read_metrics",
    "require_cost_analytics",
]
```

---

### Helper: `make_test_claims` for unit tests

```python
# src/auth/testing.py  (test helper only — not imported in production code)
from __future__ import annotations
import time
from src.auth.roles                 import PlatformRole
from src.gateway.schemas.auth_types import JWTClaims


def make_test_claims(
    *roles: PlatformRole,
    sub: str = "test-user-id",
) -> JWTClaims:
    """
    Build a JWTClaims instance with the given roles for unit testing.
    Avoids any JWT signature verification — for tests only.
    """
    return JWTClaims(
        sub                = sub,
        preferred_username = "testuser",
        email              = "testuser@example.com",
        realm_access       = {"roles": [r.value for r in roles]},
        resource_access    = {},
        exp                = int(time.time()) + 3600,
        iat                = int(time.time()),
        iss                = "https://keycloak.test/realms/contextiq",
    )
```

## Acceptance Criteria

- [ ] `require_permission(Permission.MANAGE_POLICIES)` raises HTTP 403 for a `DEVELOPER` JWT and returns `JWTClaims` for a `SECURITY_OFFICER` JWT (AC-3)
- [ ] `require_admin` raises HTTP 403 for every non-`ADMIN` role (AC-3)
- [ ] All 7 named role callables (`require_developer`, `require_platform_engineer`, etc.) are importable from `src.auth` (AC-1)
- [ ] Every HTTP 403 denial emits a `WARNING` log line containing `user`, `user_roles`, and the required permission or role (AC-6 — audit-friendly denial logging)
- [ ] `ADMIN` role passes every `require_permission()` check regardless of which permission is specified (ADMIN implicit super-role)
- [ ] `require_permission` and `require_roles` are distinct: `require_permission` reads from `ROLE_PERMISSION_MATRIX`; `require_roles` is a direct role set check

## Dependencies

- TASK-US042-01 — `PlatformRole`, `Permission`, `ROLE_PERMISSION_MATRIX`, `decode_jwt_claims`, `JWTClaimsDep`

## Definition of Done

- [ ] `mypy --strict` passes on `rbac.py`; no `ruff` lint errors
- [ ] Unit tests: matrix-driven permission checks, role-set checks, ADMIN super-role, denial log emission
