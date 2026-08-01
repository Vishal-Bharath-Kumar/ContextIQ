from __future__ import annotations

import uuid
from types import SimpleNamespace

from src.gateway.mcp_handler import _build_initial_state, _merge_request_identity
from src.gateway.schemas.auth_types import JWTClaims


def _make_claims() -> JWTClaims:
    return JWTClaims(
        sub="user-123",
        iss="https://example.test/realms/contextiq",
        exp=1_900_000_000,
        iat=1_800_000_000,
        preferred_username="admin",
        realm_access={"roles": ["admin", "developer"]},
    )


def test_merge_request_identity_uses_jwt_claims_when_body_omits_identity() -> None:
    request = SimpleNamespace(state=SimpleNamespace(jwt_claims=_make_claims()))

    merged = _merge_request_identity(request, {"prompt": "debug auth flow"})

    assert merged["user_id"] == "user-123"
    assert merged["username"] == "admin"
    assert set(merged["roles"]) == {"admin", "developer"}
    assert merged["jwt_claims"]["sub"] == "user-123"


def test_merge_request_identity_preserves_explicit_body_values() -> None:
    request = SimpleNamespace(state=SimpleNamespace(jwt_claims=_make_claims()))

    merged = _merge_request_identity(
        request,
        {
            "prompt": "debug auth flow",
            "user_id": "body-user",
            "username": "body-admin",
            "roles": ["auditor"],
        },
    )

    assert merged["user_id"] == "body-user"
    assert merged["username"] == "body-admin"
    assert merged["roles"] == ["auditor"]


def test_build_initial_state_carries_identity_and_jwt_claims() -> None:
    claims = _make_claims().model_dump(mode="python")

    state = _build_initial_state(
        uuid.uuid4(),
        {
            "tool_name": "context_query",
            "prompt": "debug auth flow",
            "user_id": "user-123",
            "username": "admin",
            "roles": ["admin"],
            "jwt_claims": claims,
            "tenant_id": "tenant-abc",
        },
    )

    assert state["user_id"] == "user-123"
    assert state["username"] == "admin"
    assert state["roles"] == ["admin"]
    assert state["jwt_claims"]["sub"] == "user-123"
    assert state["tenant_id"] == "tenant-abc"