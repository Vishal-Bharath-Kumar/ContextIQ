"""
src.auth public API — re-exports for the ContextIQ RBAC module.

Import from ``src.auth`` rather than from individual sub-modules so that
internal refactoring does not affect call sites.
"""
from src.auth.dependencies import JWTClaimsDep, decode_jwt_claims
from src.auth.rbac import (
    require_admin,
    require_auditor,
    require_context_tools,
    require_cost_analytics,
    require_developer,
    require_devops,
    require_manage_connectors,
    require_manage_models,
    require_manage_policies,
    require_manager,
    require_permission,
    require_platform_engineer,
    require_read_metrics,
    require_read_traces,
    require_roles,
    require_security_officer,
)
from src.auth.roles import ROLE_PERMISSION_MATRIX, Permission, PlatformRole, roles_for

__all__ = [
    # Roles & permissions (TASK-US042-01)
    "PlatformRole",
    "Permission",
    "ROLE_PERMISSION_MATRIX",
    "roles_for",
    # JWT dependency (TASK-US042-01)
    "decode_jwt_claims",
    "JWTClaimsDep",
    # RBAC factories (TASK-US042-02)
    "require_permission",
    "require_roles",
    # Named role-based callables
    "require_developer",
    "require_platform_engineer",
    "require_security_officer",
    "require_auditor",
    "require_manager",
    "require_admin",
    "require_devops",
    # Named permission-based callables
    "require_context_tools",
    "require_manage_connectors",
    "require_manage_models",
    "require_manage_policies",
    "require_read_traces",
    "require_read_metrics",
    "require_cost_analytics",
]
