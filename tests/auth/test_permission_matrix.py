"""
Unit tests for PlatformRole, Permission, ROLE_PERMISSION_MATRIX,
and JWTClaims RBAC helpers.

Coverage:
  - ADMIN super-role passes all permissions (AC-1)
  - Matrix internal consistency: all permissions reachable (AC-2)
  - Specific allow/deny pairs from the permission matrix (AC-2)
  - Case-insensitive role matching (AC-4)
"""
from __future__ import annotations

import time

import pytest

from src.auth.roles import ROLE_PERMISSION_MATRIX, Permission, PlatformRole
from src.auth.testing import make_test_claims
from src.gateway.schemas.auth_types import JWTClaims


class TestAdminSuperRole:
    """AC-1: ADMIN passes every permission check."""

    @pytest.mark.parametrize("permission", list(Permission))
    def test_admin_passes_all_permissions(self, permission: Permission) -> None:
        claims = make_test_claims(PlatformRole.ADMIN)
        assert claims.has_permission(permission), f"ADMIN should pass {permission}"


class TestRolePermissionMatrix:
    """AC-2: Verify the matrix is internally consistent and matches design."""

    def test_all_permissions_have_at_least_one_allowed_role(self) -> None:
        """No permission should be completely unreachable."""
        for perm, roles in ROLE_PERMISSION_MATRIX.items():
            assert len(roles) >= 1, f"{perm} has no allowed roles"

    def test_developer_cannot_manage_policies(self) -> None:
        claims = make_test_claims(PlatformRole.DEVELOPER)
        assert not claims.has_permission(Permission.MANAGE_POLICIES)

    def test_security_officer_can_manage_policies(self) -> None:
        claims = make_test_claims(PlatformRole.SECURITY_OFFICER)
        assert claims.has_permission(Permission.MANAGE_POLICIES)

    def test_auditor_can_read_traces(self) -> None:
        claims = make_test_claims(PlatformRole.AUDITOR)
        assert claims.has_permission(Permission.READ_TRACES)

    def test_auditor_cannot_call_context_tools(self) -> None:
        claims = make_test_claims(PlatformRole.AUDITOR)
        assert not claims.has_permission(Permission.CALL_CONTEXT_TOOLS)

    def test_manager_can_read_cost_analytics(self) -> None:
        claims = make_test_claims(PlatformRole.MANAGER)
        assert claims.has_permission(Permission.READ_COST_ANALYTICS)

    def test_manager_cannot_manage_connectors(self) -> None:
        claims = make_test_claims(PlatformRole.MANAGER)
        assert not claims.has_permission(Permission.MANAGE_CONNECTORS)

    def test_devops_sre_can_read_metrics(self) -> None:
        claims = make_test_claims(PlatformRole.DEVOPS_SRE)
        assert claims.has_permission(Permission.READ_METRICS)

    def test_devops_sre_cannot_manage_policies(self) -> None:
        claims = make_test_claims(PlatformRole.DEVOPS_SRE)
        assert not claims.has_permission(Permission.MANAGE_POLICIES)


class TestCaseInsensitiveRoles:
    """AC-4: Role matching is case-insensitive."""

    def test_uppercase_role_in_jwt_is_accepted(self) -> None:
        now = int(time.time())
        claims = JWTClaims(
            sub="u1",
            iss="https://keycloak.test/realms/contextiq",
            exp=now + 3600,
            iat=now,
            preferred_username="u1",
            realm_access={"roles": ["SECURITY_OFFICER"]},  # uppercase from IdP
            resource_access={},
        )
        assert claims.has_role(PlatformRole.SECURITY_OFFICER)

    def test_mixed_case_role_is_accepted(self) -> None:
        now = int(time.time())
        claims = JWTClaims(
            sub="u2",
            iss="https://keycloak.test/realms/contextiq",
            exp=now + 3600,
            iat=now,
            preferred_username="u2",
            realm_access={"roles": ["Platform_Engineer"]},
            resource_access={},
        )
        assert claims.has_role(PlatformRole.PLATFORM_ENGINEER)

    def test_client_level_role_is_merged(self) -> None:
        """AC-4: resource_access client roles are merged with realm_access roles."""
        now = int(time.time())
        claims = JWTClaims(
            sub="u3",
            iss="https://keycloak.test/realms/contextiq",
            exp=now + 3600,
            iat=now,
            realm_access={},
            resource_access={"contextiq-api": {"roles": ["auditor"]}},
        )
        assert claims.has_role(PlatformRole.AUDITOR)
        assert claims.has_permission(Permission.READ_TRACES)
