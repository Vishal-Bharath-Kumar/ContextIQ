from __future__ import annotations

from enum import StrEnum


class PlatformRole(StrEnum):
    """
    AC-1: the seven canonical platform roles.

    Values are lowercase to match Keycloak realm-role names. Role matching in
    JWTClaims.has_role() is case-insensitive, so "ADMIN" and "admin" both
    resolve to PlatformRole.ADMIN.
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
    Named permission atoms. Each permission covers a logical endpoint group.
    The permission-to-role mapping is defined in ROLE_PERMISSION_MATRIX.
    """

    # MCP tool call (context retrieval) — EP-001 MCP gateway
    CALL_CONTEXT_TOOLS  = "call_context_tools"

    # Knowledge source / connector CRUD — EP-008, EP-013 Admin Portal
    MANAGE_CONNECTORS   = "manage_connectors"

    # AI model registry and routing weights — EP-006, EP-013 Admin Portal
    MANAGE_MODELS       = "manage_models"

    # Governance policy lifecycle — EP-010, EP-013 Admin Portal
    MANAGE_POLICIES     = "manage_policies"

    # Execution trace read access — EP-011
    READ_TRACES         = "read_traces"

    # Platform metrics and observability
    READ_METRICS        = "read_metrics"

    # LLM cost analytics — EP-012 US-037, EP-013 US-041
    READ_COST_ANALYTICS = "read_cost_analytics"

    # Full administrative access (Admin Portal shell, user management)
    ADMIN_ALL           = "admin_all"


# ---------------------------------------------------------------------------
# AC-2: Role-to-permission mapping (single source of truth for all RBAC).
#
# Reading the matrix: ROLE_PERMISSION_MATRIX[permission] returns the frozenset
# of PlatformRoles that may exercise that permission.
#
# ADMIN is listed explicitly in each set for documentation clarity, but
# JWTClaims.has_permission() also short-circuits on ADMIN before consulting
# the matrix — ensuring ADMIN always passes even for unknown permissions.
# ---------------------------------------------------------------------------
ROLE_PERMISSION_MATRIX: dict[Permission, frozenset[PlatformRole]] = {

    Permission.CALL_CONTEXT_TOOLS: frozenset({
        PlatformRole.DEVELOPER,
        PlatformRole.PLATFORM_ENGINEER,
        PlatformRole.ADMIN,
    }),

    Permission.MANAGE_CONNECTORS: frozenset({
        PlatformRole.PLATFORM_ENGINEER,
        PlatformRole.ADMIN,
    }),

    Permission.MANAGE_MODELS: frozenset({
        PlatformRole.PLATFORM_ENGINEER,
        PlatformRole.ADMIN,
    }),

    Permission.MANAGE_POLICIES: frozenset({
        PlatformRole.SECURITY_OFFICER,
        PlatformRole.ADMIN,
    }),

    Permission.READ_TRACES: frozenset({
        PlatformRole.AUDITOR,
        PlatformRole.DEVOPS_SRE,
        PlatformRole.SECURITY_OFFICER,
        PlatformRole.ADMIN,
    }),

    Permission.READ_METRICS: frozenset({
        PlatformRole.DEVOPS_SRE,
        PlatformRole.PLATFORM_ENGINEER,
        PlatformRole.ADMIN,
    }),

    Permission.READ_COST_ANALYTICS: frozenset({
        PlatformRole.MANAGER,
        PlatformRole.PLATFORM_ENGINEER,
        PlatformRole.ADMIN,
    }),

    Permission.ADMIN_ALL: frozenset({
        PlatformRole.ADMIN,
    }),
}


def roles_for(permission: Permission) -> frozenset[PlatformRole]:
    """Return the set of roles permitted to exercise ``permission``."""
    return ROLE_PERMISSION_MATRIX[permission]
