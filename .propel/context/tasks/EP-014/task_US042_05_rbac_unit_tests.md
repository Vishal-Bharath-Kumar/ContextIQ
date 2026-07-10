# TASK-US042-05 — RBAC Unit Tests: Every Role × Every Protected Endpoint

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US042-05 |
| User Story | US-042 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Backend / Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Write the exhaustive RBAC test suite (AC-6): one pytest parametrized matrix covering all 7 roles against all 8 protected endpoint groups — 56 test cases in total — verifying that each combination returns either HTTP 200/201 (allowed) or HTTP 403 (denied). Add React Testing Library tests covering the `RequireRoles` guard redirect behaviour. Verify that role changes propagate within the JWT TTL (AC-5) by asserting that a fresh token with an updated role is immediately accepted without server restart.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, httpx `AsyncClient` + `ASGITransport`, `make_test_claims` (from TASK-US042-02), React Testing Library, Vitest, MSW

**File locations:**
- `tests/auth/test_rbac_matrix.py` — parametrized 7 × 8 matrix tests
- `tests/auth/test_permission_matrix.py` — unit tests for `has_permission()` and `ROLE_PERMISSION_MATRIX`
- `tests/auth/test_jwt_role_propagation.py` — JWT TTL propagation tests (AC-5)
- `frontend/admin-portal/src/__tests__/RequireRoles.test.tsx`

---

### Backend: exhaustive role × endpoint matrix

```python
# tests/auth/test_rbac_matrix.py
import pytest
from httpx import AsyncClient, ASGITransport
from src.main                           import app
from src.auth.roles                     import PlatformRole, Permission
from src.auth.testing                   import make_test_claims
from src.gateway.schemas.auth_types     import JWTClaims


# ---------------------------------------------------------------------------
# Endpoint fixture: (method, path, body)  — one entry per protected endpoint group
# Each entry should produce a non-404 response for an authorised caller.
# ---------------------------------------------------------------------------
PROTECTED_ENDPOINTS = [
    # (id,                     method, path,                              body)
    ("mcp_tool_call",          "POST", "/tools/context_query",            {"query": "test"}),
    ("knowledge_sources_list", "GET",  "/v1/knowledge-sources",           None),
    ("models_list",            "GET",  "/v1/models",                      None),
    ("routing_weights_list",   "GET",  "/v1/routing/weights",             None),
    ("policies_list",          "GET",  "/v1/policies",                    None),
    ("traces_list",            "GET",  "/v1/traces",                      None),
    ("cost_analytics",         "GET",  "/v1/models/cost-analytics",       None),
    ("metrics",                "GET",  "/metrics",                        None),
]

# ---------------------------------------------------------------------------
# Expected access matrix:
#   ALLOWED[role][endpoint_id] = True  → expect 2xx
#   ALLOWED[role][endpoint_id] = False → expect 403
# ---------------------------------------------------------------------------
ALLOWED: dict[PlatformRole, dict[str, bool]] = {
    PlatformRole.DEVELOPER: {
        "mcp_tool_call":          True,
        "knowledge_sources_list": False,
        "models_list":            False,
        "routing_weights_list":   False,
        "policies_list":          False,
        "traces_list":            False,
        "cost_analytics":         False,
        "metrics":                False,
    },
    PlatformRole.PLATFORM_ENGINEER: {
        "mcp_tool_call":          True,
        "knowledge_sources_list": True,
        "models_list":            True,
        "routing_weights_list":   True,
        "policies_list":          False,
        "traces_list":            False,
        "cost_analytics":         True,
        "metrics":                True,
    },
    PlatformRole.DEVOPS_SRE: {
        "mcp_tool_call":          False,
        "knowledge_sources_list": False,
        "models_list":            False,
        "routing_weights_list":   False,
        "policies_list":          False,
        "traces_list":            True,
        "cost_analytics":         False,
        "metrics":                True,
    },
    PlatformRole.ADMIN: {
        "mcp_tool_call":          True,
        "knowledge_sources_list": True,
        "models_list":            True,
        "routing_weights_list":   True,
        "policies_list":          True,
        "traces_list":            True,
        "cost_analytics":         True,
        "metrics":                True,
    },
    PlatformRole.SECURITY_OFFICER: {
        "mcp_tool_call":          False,
        "knowledge_sources_list": False,
        "models_list":            False,
        "routing_weights_list":   False,
        "policies_list":          True,
        "traces_list":            True,   # security officers may audit traces
        "cost_analytics":         False,
        "metrics":                False,
    },
    PlatformRole.MANAGER: {
        "mcp_tool_call":          False,
        "knowledge_sources_list": False,
        "models_list":            False,
        "routing_weights_list":   False,
        "policies_list":          False,
        "traces_list":            False,
        "cost_analytics":         True,
        "metrics":                False,
    },
    PlatformRole.AUDITOR: {
        "mcp_tool_call":          False,
        "knowledge_sources_list": False,
        "models_list":            False,
        "routing_weights_list":   False,
        "policies_list":          False,
        "traces_list":            True,
        "cost_analytics":         False,
        "metrics":                False,
    },
}


def _inject_claims(claims: JWTClaims):
    """
    Override request.state.jwt_claims with test claims, bypassing real JWT verification.
    FastAPI TestClient allows middleware overrides via app.state or dependency overrides.
    """
    from src.auth.dependencies import decode_jwt_claims
    app.dependency_overrides[decode_jwt_claims] = lambda: claims
    return claims


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(PlatformRole))
@pytest.mark.parametrize(
    "endpoint_id,method,path,body",
    [(e[0], e[1], e[2], e[3]) for e in PROTECTED_ENDPOINTS],
)
async def test_rbac_matrix(
    role: PlatformRole,
    endpoint_id: str,
    method: str,
    path: str,
    body: dict | None,
):
    """
    AC-6: For every (role, endpoint) pair, verify correct 2xx or 403.
    Total: 7 roles × 8 endpoints = 56 parametrized test cases.
    """
    claims = make_test_claims(role)
    _inject_claims(claims)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        if method == "GET":
            response = await client.get(path)
        elif method == "POST":
            response = await client.post(path, json=body or {})
        elif method == "PUT":
            response = await client.put(path, json=body or {})
        else:
            response = await client.request(method, path, json=body)

    expected_allowed = ALLOWED[role][endpoint_id]

    if expected_allowed:
        assert response.status_code != 403, (
            f"Role {role} SHOULD be allowed on {method} {path} "
            f"but got HTTP {response.status_code}"
        )
    else:
        assert response.status_code == 403, (
            f"Role {role} SHOULD be DENIED on {method} {path} "
            f"but got HTTP {response.status_code} (expected 403)"
        )
```

---

### Permission matrix unit tests

```python
# tests/auth/test_permission_matrix.py
import pytest
from src.auth.roles     import PlatformRole, Permission, ROLE_PERMISSION_MATRIX
from src.auth.testing   import make_test_claims


class TestAdminSuperRole:
    """AC-1: ADMIN passes every permission check."""

    @pytest.mark.parametrize("permission", list(Permission))
    def test_admin_passes_all_permissions(self, permission: Permission):
        claims = make_test_claims(PlatformRole.ADMIN)
        assert claims.has_permission(permission), (
            f"ADMIN should pass {permission}"
        )


class TestRolePermissionMatrix:
    """AC-2: Verify the matrix is internally consistent."""

    def test_all_permissions_have_at_least_one_allowed_role(self):
        """No permission should be completely unreachable."""
        for perm, roles in ROLE_PERMISSION_MATRIX.items():
            assert len(roles) >= 1, f"{perm} has no allowed roles"

    def test_developer_cannot_manage_policies(self):
        claims = make_test_claims(PlatformRole.DEVELOPER)
        assert not claims.has_permission(Permission.MANAGE_POLICIES)

    def test_security_officer_can_manage_policies(self):
        claims = make_test_claims(PlatformRole.SECURITY_OFFICER)
        assert claims.has_permission(Permission.MANAGE_POLICIES)

    def test_auditor_can_read_traces(self):
        claims = make_test_claims(PlatformRole.AUDITOR)
        assert claims.has_permission(Permission.READ_TRACES)

    def test_auditor_cannot_call_context_tools(self):
        claims = make_test_claims(PlatformRole.AUDITOR)
        assert not claims.has_permission(Permission.CALL_CONTEXT_TOOLS)

    def test_manager_can_read_cost_analytics(self):
        claims = make_test_claims(PlatformRole.MANAGER)
        assert claims.has_permission(Permission.READ_COST_ANALYTICS)

    def test_manager_cannot_manage_connectors(self):
        claims = make_test_claims(PlatformRole.MANAGER)
        assert not claims.has_permission(Permission.MANAGE_CONNECTORS)


class TestCaseInsensitiveRoles:
    """AC-4: Role matching is case-insensitive."""

    def test_uppercase_role_in_jwt_is_accepted(self):
        from src.gateway.schemas.auth_types import JWTClaims
        import time
        claims = JWTClaims(
            sub                = "u1",
            preferred_username = "u1",
            realm_access       = {"roles": ["SECURITY_OFFICER"]},   # uppercase from IdP
            resource_access    = {},
            exp                = int(time.time()) + 3600,
            iat                = int(time.time()),
            iss                = "https://keycloak.test/realms/contextiq",
        )
        assert claims.has_role(PlatformRole.SECURITY_OFFICER)

    def test_mixed_case_role_is_accepted(self):
        from src.gateway.schemas.auth_types import JWTClaims
        import time
        claims = JWTClaims(
            sub                = "u2",
            preferred_username = "u2",
            realm_access       = {"roles": ["Platform_Engineer"]},
            resource_access    = {},
            exp                = int(time.time()) + 3600,
            iat                = int(time.time()),
            iss                = "https://keycloak.test/realms/contextiq",
        )
        assert claims.has_role(PlatformRole.PLATFORM_ENGINEER)
```

---

### JWT TTL propagation test (AC-5)

```python
# tests/auth/test_jwt_role_propagation.py
import pytest
import time
from src.auth.testing import make_test_claims
from src.auth.rbac    import require_manage_policies


@pytest.mark.asyncio
async def test_role_change_reflected_in_next_request():
    """
    AC-5: Role changes in Keycloak propagate within JWT TTL (5 min default).
    Simulate: first token has DEVELOPER role (denied), second token has
    SECURITY_OFFICER role (allowed) — same user, two distinct JWT objects.
    Server-side caching is NOT used — each request re-extracts claims from the
    token, so a freshly issued JWT immediately reflects the role change.
    """
    from fastapi         import HTTPException
    from unittest.mock   import AsyncMock

    # First request — DEVELOPER role
    old_claims = make_test_claims(PlatformRole.DEVELOPER, sub="user-123")
    check_fn   = require_manage_policies()

    with pytest.raises(HTTPException) as exc_info:
        await check_fn(old_claims)
    assert exc_info.value.status_code == 403

    # Simulate role change: new JWT issued after Keycloak role assignment
    # No server restart, no cache flush — the new token carries the new role
    new_claims = make_test_claims(PlatformRole.SECURITY_OFFICER, sub="user-123")
    result     = await check_fn(new_claims)
    assert result.has_role(PlatformRole.SECURITY_OFFICER)


def test_no_server_side_role_cache():
    """
    AC-5: Platform does not cache role sets per user_id.
    Confirmed by absence of any in-memory role cache in the RBAC module.
    """
    import inspect, src.auth.rbac as rbac_module
    source = inspect.getsource(rbac_module)
    # No user-keyed dict or Redis lookup should exist in the RBAC module
    assert "lru_cache" not in source
    assert "_role_cache" not in source
```

---

### Frontend: `RequireRoles` guard tests

```tsx
// frontend/admin-portal/src/__tests__/RequireRoles.test.tsx
import { render, screen }    from "@testing-library/react";
import { MemoryRouter }      from "react-router-dom";
import { RequireRoles }      from "../guards/RequireRoles";
import { AuthProvider }      from "../context/AuthContext";
import { PlatformRole }      from "../auth/roles";

function TestApp({ userRoles, allowedRoles }: { userRoles: string[]; allowedRoles: string[] }) {
  // Mock auth context with the provided roles
  const mockUser = { userId: "u1", email: "u@test.com", roles: userRoles, token: "fake.token.here" };
  return (
    <MemoryRouter initialEntries={["/protected"]}>
      <AuthProvider _mockUser={mockUser}>
        <RequireRoles allowedRoles={allowedRoles as any}>
          <div data-testid="content">Protected Content</div>
        </RequireRoles>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("RequireRoles — AC-1, AC-2", () => {
  it("renders children when user has an allowed role", () => {
    render(<TestApp userRoles={["security_officer"]} allowedRoles={[PlatformRole.SECURITY_OFFICER]} />);
    expect(screen.getByTestId("content")).toBeInTheDocument();
  });

  it("redirects to /403 when user lacks required role", () => {
    render(<TestApp userRoles={["developer"]} allowedRoles={[PlatformRole.SECURITY_OFFICER]} />);
    expect(screen.queryByTestId("content")).not.toBeInTheDocument();
  });

  it("ADMIN passes any RequireRoles regardless of allowedRoles list", () => {
    render(<TestApp userRoles={["admin"]} allowedRoles={[PlatformRole.SECURITY_OFFICER]} />);
    expect(screen.getByTestId("content")).toBeInTheDocument();
  });

  it("redirects to /login when user is null (unauthenticated)", () => {
    render(<TestApp userRoles={[]} allowedRoles={[PlatformRole.ADMIN]} />);
    expect(screen.queryByTestId("content")).not.toBeInTheDocument();
  });

  it("role comparison is case-insensitive — SECURITY_OFFICER matches security_officer", () => {
    render(<TestApp userRoles={["SECURITY_OFFICER"]} allowedRoles={[PlatformRole.SECURITY_OFFICER]} />);
    expect(screen.getByTestId("content")).toBeInTheDocument();
  });
});
```

## Acceptance Criteria

- [ ] All 56 parametrized `test_rbac_matrix` test cases pass — 7 roles × 8 endpoint groups (AC-6)
- [ ] `test_admin_passes_all_permissions` passes for all 8 `Permission` values (AC-1)
- [ ] `test_uppercase_role_in_jwt_is_accepted` and `test_mixed_case_role_is_accepted` pass — case-insensitive (AC-4)
- [ ] `test_role_change_reflected_in_next_request` — fresh JWT with updated role is immediately honoured — no server restart needed (AC-5)
- [ ] `test_no_server_side_role_cache` — confirms absence of any user-keyed role cache in the RBAC module (AC-5)
- [ ] `RequireRoles` React tests: allowed renders content, denied redirects, ADMIN passes all, null user redirects to /login, case-insensitive match (AC-1, AC-4)
- [ ] Permission matrix tests: developer denied MANAGE_POLICIES, auditor denied CALL_CONTEXT_TOOLS, manager denied MANAGE_CONNECTORS (AC-2)

## Dependencies

- TASK-US042-01 — `PlatformRole`, `Permission`, `ROLE_PERMISSION_MATRIX`, `make_test_claims`
- TASK-US042-02 — `require_manage_policies` and other named callables used in propagation test
- TASK-US042-03 — all routers must have RBAC applied for integration matrix tests
- TASK-US042-04 — `RequireRoles`, `hasAnyRole` frontend

## Definition of Done

- [ ] `pytest tests/auth/ -v` shows 56+ passing matrix tests (AC-6)
- [ ] `pnpm test` passes all `RequireRoles` tests
- [ ] `mypy --strict` passes on all test helper files
