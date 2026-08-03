"""
JWT claims model for ContextIQ.

This module defines JWTClaims — the Pydantic model populated by JWTAuthMiddleware
(TASK-US004-01) from the verified Keycloak JWT on every authenticated request.
It is stored in request.state.jwt_claims and retrieved by the decode_jwt_claims
FastAPI dependency (src.auth.dependencies).

RBAC helpers (has_role, has_permission) were added in TASK-US042-01.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

# Deferred to break the circular import:
#   auth_types → src.auth.roles → src.auth.__init__ → dependencies → auth_types
# At runtime the imports are resolved lazily inside each method that needs them.
if TYPE_CHECKING:
    from src.auth.roles import Permission, PlatformRole, ROLE_PERMISSION_MATRIX


class JWTClaims(BaseModel):
    """
    Decoded and verified Keycloak JWT payload.

    Keycloak embeds realm-level roles in realm_access.roles and per-client
    roles in resource_access.<client-id>.roles.  The roles property merges
    both sources so that downstream RBAC checks are source-agnostic.

    Extra fields present in the raw JWT (e.g. azp, session_state, acr) are
    silently ignored.
    """

    model_config = ConfigDict(
        extra="ignore",   # tolerate Keycloak-specific fields not listed here
        frozen=True,      # JWT claims are immutable after construction
    )

    # ---- Standard OIDC / JWT claims ----------------------------------------
    sub:                str
    iss:                str
    exp:                int
    iat:                int
    jti:                str | None              = None
    aud:                str | list[str] | None  = None

    # ---- Keycloak user profile claims ---------------------------------------
    email:              str | None  = None
    email_verified:     bool        = False
    preferred_username: str | None  = None
    name:               str | None  = None
    given_name:         str | None  = None
    family_name:        str | None  = None

    # ---- Keycloak role claims -----------------------------------------------
    # realm_access: {"roles": ["admin", "developer", ...]}
    realm_access:    dict[str, list[str]]            = Field(default_factory=dict)
    # resource_access: {"my-client": {"roles": ["client_role"]}, ...}
    resource_access: dict[str, dict[str, list[str]]] = Field(default_factory=dict)

    # -------------------------------------------------------------------------
    # RBAC helpers — TASK-US042-01
    # -------------------------------------------------------------------------

    @property
    def roles(self) -> frozenset[str]:
        """
        AC-4: Merge realm-level and client-level roles from the Keycloak JWT.

        Keycloak embeds realm roles in realm_access.roles and client roles in
        resource_access.<client-id>.roles.  Both sources are merged here so
        that has_role() / has_permission() are source-agnostic.
        """
        realm_roles: set[str] = set(self.realm_access.get("roles", []))
        client_roles: set[str] = set()
        for client_data in self.resource_access.values():
            client_roles.update(client_data.get("roles", []))
        return frozenset(realm_roles | client_roles)

    def has_role(self, role: PlatformRole) -> bool:
        """
        Case-insensitive role membership check — AC-4.

        Normalises both the token roles and the target role to lowercase
        so that "ADMIN" and "admin" both match PlatformRole.ADMIN.
        """
        from src.auth.roles import PlatformRole as _PlatformRole  # noqa: PLC0415
        normalised: frozenset[str] = frozenset(r.lower() for r in self.roles)
        return role.value.lower() in normalised

    def has_any_role(self, *roles: PlatformRole) -> bool:
        """Return True if the token contains at least one of ``roles``."""
        return any(self.has_role(r) for r in roles)

    def has_permission(self, permission: Permission) -> bool:
        """
        AC-2: Check permission against the ROLE_PERMISSION_MATRIX.

        ADMIN is an implicit super-role — any token with ADMIN passes every
        permission check without consulting the matrix.  For all other roles
        the matrix is the authoritative source.
        """
        from src.auth.roles import ROLE_PERMISSION_MATRIX as _MATRIX, PlatformRole as _PlatformRole  # noqa: PLC0415
        if self.has_role(_PlatformRole.ADMIN):
            return True
        allowed_roles: frozenset[_PlatformRole] = _MATRIX.get(
            permission, frozenset()
        )
        return self.has_any_role(*allowed_roles)


# ---------------------------------------------------------------------------
# TASK-US004-01: Structured auth error response model
# ---------------------------------------------------------------------------

class AuthError(BaseModel):
    """Structured authentication error body returned by JWTAuthMiddleware.

    Conforms to the error shape documented in TASK-US004-01 so API clients
    can branch on ``error`` without parsing the human-readable ``message``.
    """

    error: str
    message: str | None = None
