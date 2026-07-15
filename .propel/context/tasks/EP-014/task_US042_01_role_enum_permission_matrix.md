# TASK-US042-01 — `PlatformRole` Enum, Permission Matrix, and `decode_jwt_claims` Dependency

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US042-01 |
| User Story | US-042 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Define the seven canonical `PlatformRole` values (AC-1), the `Permission` enum that models every protected action category, and the documented `ROLE_PERMISSION_MATRIX` that maps permissions to their allowed role sets (AC-2). Extend the existing `JWTClaims` model (US-004 TASK-US004-03) with a `has_role()` helper. Provide a `decode_jwt_claims` FastAPI dependency that extracts and validates roles from the Keycloak `realm_access.roles` claim on every request (AC-4). This module is the single source of truth consumed by all RBAC dependency factories in TASK-US042-02.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, FastAPI `Depends`

**File locations:**
- `src/auth/roles.py` — `PlatformRole`, `Permission`, `ROLE_PERMISSION_MATRIX`
- `src/auth/dependencies.py` — `decode_jwt_claims` FastAPI dependency (replaces ad-hoc `require_admin_role` in `src/api/admin/dependencies.py`)
- `src/gateway/schemas/auth_types.py` — extend `JWTClaims` with `has_role()` and `has_permission()` (TASK-US004-03 file)

---

### `PlatformRole` and `Permission` enums

```python
# src/auth/roles.py
from __future__ import annotations
from enum import StrEnum


class PlatformRole(StrEnum):
    """
    AC-1: the seven platform roles.
    Values are lowercase to match Keycloak realm-role names case-insensitively.
    """
    DEVELOPER          = "developer"
    PLATFORM_ENGINEER  = "platform_engineer"
    DEVOPS_SRE         = "devops_sre"
    ADMIN              = "admin"
    SECURITY_OFFICER   = "security_officer"
    MANAGER            = "manager"
    AUDITOR            = "auditor"


class Permission(StrEnum):
    """
    Named permission atoms. Each permission covers an endpoint group.
    Permission-to-role mapping is defined in ROLE_PERMISSION_MATRIX below.
    """
    # MCP tool call (context retrieval)
    CALL_CONTEXT_TOOLS    = "call_context_tools"

    # Knowledge source management
    MANAGE_CONNECTORS     = "manage_connectors"

    # AI model registry and routing weights
    MANAGE_MODELS         = "manage_models"

    # Governance policy lifecycle
    MANAGE_POLICIES       = "manage_policies"

    # Execution trace read access
    READ_TRACES           = "read_traces"

    # Platform metrics and observability
    READ_METRICS          = "read_metrics"

    # LLM cost analytics
    READ_COST_ANALYTICS   = "read_cost_analytics"

    # Full admin access (all operations)
    ADMIN_ALL             = "admin_all"
```

---

### `ROLE_PERMISSION_MATRIX` — AC-2: documented and enforced

```python
# src/auth/roles.py  (continued)
#
# AC-2: Role-to-permission mapping.
# The matrix is the single authoritative source for all RBAC enforcement in
# TASK-US042-02 (dependency factories) and TASK-US042-03 (route application).
#
# Reading the matrix: ROLE_PERMISSION_MATRIX[permission] returns the set of
# roles that are ALLOWED to exercise that permission. The ADMIN role is
# implicitly included in every permission via the `has_permission()` helper.

ROLE_PERMISSION_MATRIX: dict[Permission, frozenset[PlatformRole]] = {

    # Context tool calls (EP-001 MCP gateway — primary developer workflow)
    Permission.CALL_CONTEXT_TOOLS: frozenset({
        PlatformRole.DEVELOPER,
        PlatformRole.PLATFORM_ENGINEER,
        PlatformRole.ADMIN,
    }),

    # Knowledge source / connector CRUD (EP-008, EP-013 Admin Portal)
    Permission.MANAGE_CONNECTORS: frozenset({
        PlatformRole.PLATFORM_ENGINEER,
        PlatformRole.ADMIN,
    }),

    # Model registry, routing weights (EP-006, EP-013 Admin Portal)
    Permission.MANAGE_MODELS: frozenset({
        PlatformRole.PLATFORM_ENGINEER,
        PlatformRole.ADMIN,
    }),

    # Governance policy lifecycle (EP-010, EP-013 Admin Portal)
    Permission.MANAGE_POLICIES: frozenset({
        PlatformRole.SECURITY_OFFICER,
        PlatformRole.ADMIN,
    }),

    # Execution trace read / replay (EP-011)
    Permission.READ_TRACES: frozenset({
        PlatformRole.AUDITOR,
        PlatformRole.DEVOPS_SRE,
        PlatformRole.SECURITY_OFFICER,
        PlatformRole.ADMIN,
    }),

    # Prometheus metrics endpoint
    Permission.READ_METRICS: frozenset({
        PlatformRole.DEVOPS_SRE,
        PlatformRole.PLATFORM_ENGINEER,
        PlatformRole.ADMIN,
    }),

    # LLM cost analytics (EP-012 US-037, EP-013 US-041)
    Permission.READ_COST_ANALYTICS: frozenset({
        PlatformRole.MANAGER,
        PlatformRole.PLATFORM_ENGINEER,
        PlatformRole.ADMIN,
    }),

    # Full administrative access (Admin Portal shell, user management)
    Permission.ADMIN_ALL: frozenset({
        PlatformRole.ADMIN,
    }),
}


def roles_for(permission: Permission) -> frozenset[PlatformRole]:
    """Return the set of roles permitted to exercise `permission`."""
    return ROLE_PERMISSION_MATRIX[permission]
```

---

### Extend `JWTClaims` with RBAC helpers

```python
# src/gateway/schemas/auth_types.py  (extend TASK-US004-03 model — do NOT rewrite)
from src.auth.roles import PlatformRole, Permission, ROLE_PERMISSION_MATRIX

# Inside JWTClaims class:

    @property
    def roles(self) -> frozenset[str]:
        """
        AC-4: Merge realm-level and client-level roles from the Keycloak JWT.
        Keycloak embeds realm roles in realm_access.roles and client roles in
        resource_access.<client-id>.roles.
        """
        realm_roles  = set(self.realm_access.get("roles", []))
        client_roles: set[str] = set()
        for client_data in self.resource_access.values():
            client_roles.update(client_data.get("roles", []))
        return frozenset(realm_roles | client_roles)

    def has_role(self, role: PlatformRole) -> bool:
        """Case-insensitive role check — AC-4."""
        normalised = {r.lower() for r in self.roles}
        return role.value.lower() in normalised

    def has_any_role(self, *roles: PlatformRole) -> bool:
        """Return True if the token contains at least one of the given roles."""
        return any(self.has_role(r) for r in roles)

    def has_permission(self, permission: Permission) -> bool:
        """
        AC-2: Check permission against the ROLE_PERMISSION_MATRIX.
        ADMIN always passes (implicit super-role).
        """
        if self.has_role(PlatformRole.ADMIN):
            return True
        allowed_roles = ROLE_PERMISSION_MATRIX.get(permission, frozenset())
        return self.has_any_role(*allowed_roles)
```

---

### `decode_jwt_claims` FastAPI dependency

```python
# src/auth/dependencies.py
from __future__ import annotations
from typing     import Annotated
from fastapi    import Depends, HTTPException, Request, status
from src.gateway.schemas.auth_types import JWTClaims


def _get_verified_claims(request: Request) -> JWTClaims:
    """
    Extract the already-verified JWTClaims injected into ASGI scope state
    by JWTAuthMiddleware (TASK-US004-01).

    If claims are missing (middleware bypassed in tests), raises 401.
    """
    claims: JWTClaims | None = getattr(request.state, "jwt_claims", None)
    if claims is None:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Authentication required.",
            headers     = {"WWW-Authenticate": "Bearer"},
        )
    return claims


# Public alias — route handlers use `Depends(decode_jwt_claims)`
decode_jwt_claims = _get_verified_claims

# Type alias for annotated dependency injection
JWTClaimsDep = Annotated[JWTClaims, Depends(decode_jwt_claims)]
```

---

### Deprecate old `require_admin_role` shim

```python
# src/api/admin/dependencies.py  (replace implementation — keep function signature for backwards compat)
from src.auth.dependencies import decode_jwt_claims
from src.auth.roles        import PlatformRole
from fastapi               import Depends, HTTPException, status
from src.gateway.schemas.auth_types import JWTClaims


def require_admin_role(
    claims: JWTClaims = Depends(decode_jwt_claims),
) -> JWTClaims:
    """
    Backwards-compatible shim — delegates to the canonical RBAC system.
    New code should use require_roles(PlatformRole.ADMIN) from src.auth.rbac.
    """
    if not claims.has_role(PlatformRole.ADMIN):
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = "Admin role required.",
        )
    return claims
```

## Acceptance Criteria

- [x] `PlatformRole` defines exactly 7 roles matching the story: `DEVELOPER`, `PLATFORM_ENGINEER`, `DEVOPS_SRE`, `ADMIN`, `SECURITY_OFFICER`, `MANAGER`, `AUDITOR` (AC-1)
- [x] `ROLE_PERMISSION_MATRIX` is defined as a module-level constant and covers all 8 `Permission` values (AC-2)
- [x] `JWTClaims.has_permission(Permission.ADMIN_ALL)` returns `True` only for `ADMIN` role; `JWTClaims.has_permission(Permission.READ_TRACES)` returns `True` for `AUDITOR`, `DEVOPS_SRE`, `SECURITY_OFFICER`, and `ADMIN` (AC-2)
- [x] `JWTClaims.roles` merges both `realm_access.roles` and `resource_access.<client>.roles` — Keycloak client-level roles are honoured (AC-4)
- [x] Role matching is case-insensitive — `"ADMIN"` and `"admin"` both match `PlatformRole.ADMIN` (AC-4)
- [x] `decode_jwt_claims` reads `request.state.jwt_claims` set by `JWTAuthMiddleware` — no second JWT decode per request (AC-4, performance)

## Dependencies

- US-004 TASK-US004-01 — `JWTAuthMiddleware` sets `request.state.jwt_claims`
- US-004 TASK-US004-03 — `JWTClaims` Pydantic model extended in this task

## Definition of Done

- [x] `mypy --strict` passes on `roles.py` and `dependencies.py`
- [x] Unit tests: `has_permission()` matrix coverage, case-insensitive role match, admin implicit super-role
