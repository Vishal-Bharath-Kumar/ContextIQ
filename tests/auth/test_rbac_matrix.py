"""
RBAC integration matrix: 7 roles × 8 endpoint groups = 56 parametrized test cases.

AC-6: For every (role, endpoint) pair the test asserts:
  - allowed → response.status_code != 403  (FastAPI returns 200/201/422 etc.)
  - denied  → response.status_code == 403

The test bypasses real JWT verification by overriding the decode_jwt_claims
dependency directly via FastAPI's dependency_overrides mechanism.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth.dependencies import decode_jwt_claims
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.gateway.schemas.auth_types import JWTClaims
from src.main import app

# ---------------------------------------------------------------------------
# Endpoint fixture: (id, method, path, body)
# Each entry must have a registered route handler so that RBAC deps execute.
# ---------------------------------------------------------------------------
PROTECTED_ENDPOINTS = [
    # (id,                     method,  path,                         body)
    ("mcp_tool_call",          "POST",  "/tools/context_query",       {"query": "test"}),
    ("knowledge_sources_list", "GET",   "/v1/knowledge-sources",      None),
    ("models_list",            "GET",   "/v1/models",                 None),
    ("routing_weights_list",   "GET",   "/v1/routing/weights",        None),
    ("policies_list",          "GET",   "/v1/policies",               None),
    ("traces_list",            "GET",   "/v1/traces",                 None),
    ("cost_analytics",         "GET",   "/v1/models/cost-analytics",  None),
    ("metrics",                "GET",   "/metrics",                   None),
]

# ---------------------------------------------------------------------------
# Expected access matrix (derived from ROLE_PERMISSION_MATRIX).
# True  → 2xx expected
# False → 403 expected
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


def _inject_claims(claims: JWTClaims) -> None:
    """
    Override decode_jwt_claims with a no-arg lambda that returns test claims,
    bypassing real JWT signature verification for the duration of the test.
    Cleared by the clear_overrides fixture after each test.
    """
    app.dependency_overrides[decode_jwt_claims] = lambda: claims


@pytest.fixture(autouse=True)
def clear_overrides() -> None:  # type: ignore[return]
    """Reset dependency overrides after every test to avoid state leakage."""
    yield  # type: ignore[misc]
    app.dependency_overrides.clear()


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
    body: dict[str, object] | None,
) -> None:
    """
    AC-6: 7 roles × 8 endpoints = 56 parametrized cases.
    Each case asserts correct 2xx (allowed) or 403 (denied).
    """
    claims = make_test_claims(role)
    _inject_claims(claims)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        if method == "GET":
            response = await client.get(path)
        elif method == "POST":
            response = await client.post(path, json=body or {})
        else:
            response = await client.request(method, path, json=body)

    expected_allowed = ALLOWED[role][endpoint_id]

    if expected_allowed:
        assert response.status_code != 403, (
            f"Role {role!r} SHOULD be allowed on {method} {path} "
            f"but got HTTP {response.status_code}"
        )
    else:
        assert response.status_code == 403, (
            f"Role {role!r} SHOULD be denied on {method} {path} "
            f"but got HTTP {response.status_code} (expected 403)"
        )
