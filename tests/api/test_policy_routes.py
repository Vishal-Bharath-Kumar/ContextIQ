"""Unit tests for Admin API policy routes — TASK-US033-04.

Uses FastAPI TestClient with dependency overrides for:
  - decode_jwt_claims   → inject admin / non-admin JWTClaims
  - get_db              → AsyncMock session
  - _build_service      → AsyncMock PolicyService

Covers all acceptance criteria:
  AC-1  — POST /v1/policies returns 201 with PolicyVersion body
  AC-2  — POST /v1/policies returns 409 on duplicate (name, version)
  AC-3  — POST /v1/policies/{id}/activate returns 200 with bundle_push_ok=true
  AC-4  — POST /v1/policies/{id}/rollback?version=N returns 404 when version absent
  AC-5  — author equals JWT sub claim
  AC-6  — POST /v1/policies/{id}/activate returns 422 with errors list on bad Rego
  RBAC  — All three endpoints return 403 when caller lacks admin role
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from src.auth.dependencies import decode_jwt_claims
from src.auth.middleware import JWTAuthMiddleware
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.data.dependencies import get_db
from src.gateway.schemas.auth_types import JWTClaims
from src.governance.policy.repository import PolicyNotFoundError, PolicyRepository
from src.governance.policy.schemas import (
    ActivateResponse,
    PolicyStatus,
    PolicyVersion,
    RollbackResponse,
)
from src.governance.policy.service import (
    PolicyAlreadyActiveError,
    PolicyVersionNotFoundError,
)
from src.governance.policy.validator import RegoValidationError
from src.main import app

_POLICY_ID = uuid.uuid4()
_NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=UTC)
_AUTHOR = "user-admin-001"
_VALID_REGO = "package acl\n\nallow = true\n"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def bypass_jwt_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace JWTAuthMiddleware.dispatch with a pass-through for all policy tests."""
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

    async def _passthrough(
        self: object,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        return await call_next(request)

    monkeypatch.setattr(JWTAuthMiddleware, "dispatch", _passthrough)


@pytest.fixture
def admin_claims() -> JWTClaims:
    return make_test_claims(PlatformRole.ADMIN, sub=_AUTHOR)


@pytest.fixture
def non_admin_claims() -> JWTClaims:
    return make_test_claims(PlatformRole.DEVELOPER, sub="developer-001")


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def client_as_admin(admin_claims: JWTClaims, mock_session: AsyncMock) -> TestClient:
    """TestClient with admin claims and a mock DB session."""
    app.dependency_overrides[decode_jwt_claims] = lambda: admin_claims
    app.dependency_overrides[get_db] = lambda: mock_session
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(decode_jwt_claims, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client_as_non_admin(non_admin_claims: JWTClaims, mock_session: AsyncMock) -> TestClient:
    """TestClient with developer (non-admin) claims."""
    app.dependency_overrides[decode_jwt_claims] = lambda: non_admin_claims
    app.dependency_overrides[get_db] = lambda: mock_session
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(decode_jwt_claims, None)
    app.dependency_overrides.pop(get_db, None)


def _make_policy_version(**overrides: str | PolicyStatus | uuid.UUID | datetime | None) -> PolicyVersion:
    defaults: dict[str, Any] = {
        "id": _POLICY_ID,
        "policy_group": "acl",
        "version": "1.0.0",
        "description": "Test policy",
        "rego_body": _VALID_REGO,
        "status": PolicyStatus.DRAFT,
        "author": _AUTHOR,
        "activated_at": None,
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return PolicyVersion(**defaults)


def _make_activate_response(**overrides: str | bool | datetime) -> ActivateResponse:
    defaults: dict[str, Any] = {
        "activated_version": "1.0.0",
        "bundle_push_ok": True,
        "activated_at": _NOW,
    }
    defaults.update(overrides)
    return ActivateResponse(**defaults)


def _make_rollback_response(**overrides: str | datetime) -> RollbackResponse:
    defaults: dict[str, Any] = {
        "restored_version": "0.9.0",
        "previous_active": "1.0.0",
        "activated_at": _NOW,
    }
    defaults.update(overrides)
    return RollbackResponse(**defaults)


# ---------------------------------------------------------------------------
# RBAC — 403 when caller lacks admin role
# ---------------------------------------------------------------------------


class TestRbacForbidden:
    def test_create_policy_returns_403_for_non_admin(
        self, client_as_non_admin: TestClient
    ) -> None:
        resp = client_as_non_admin.post(
            "/v1/policies",
            json={
                "name": "acl",
                "version": "1.0.0",
                "description": "",
                "rego_body": _VALID_REGO,
            },
        )
        assert resp.status_code == 403

    def test_activate_policy_returns_403_for_non_admin(
        self, client_as_non_admin: TestClient
    ) -> None:
        resp = client_as_non_admin.post(f"/v1/policies/{_POLICY_ID}/activate")
        assert resp.status_code == 403

    def test_rollback_policy_returns_403_for_non_admin(
        self, client_as_non_admin: TestClient
    ) -> None:
        resp = client_as_non_admin.post(
            f"/v1/policies/{_POLICY_ID}/rollback?version=0.9.0"
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /v1/policies — AC-1, AC-2, AC-5
# ---------------------------------------------------------------------------


class TestCreatePolicy:
    def test_create_returns_201_with_policy_version(
        self, client_as_admin: TestClient
    ) -> None:
        """AC-1 — 201 with full PolicyVersion body."""
        policy_version = _make_policy_version()
        mock_svc = AsyncMock()
        mock_svc.create = AsyncMock(return_value=policy_version)

        with patch(
            "src.api.admin.routes.policies._build_service", return_value=mock_svc
        ):
            resp = client_as_admin.post(
                "/v1/policies",
                json={
                    "name": "acl",
                    "version": "1.0.0",
                    "description": "Test policy",
                    "rego_body": _VALID_REGO,
                },
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["policy_group"] == "acl"
        assert body["version"] == "1.0.0"
        assert body["status"] == "draft"

    def test_create_passes_jwt_sub_as_author(
        self, client_as_admin: TestClient
    ) -> None:
        """AC-5 — author stored from JWT sub claim."""
        policy_version = _make_policy_version(author=_AUTHOR)
        mock_svc = AsyncMock()
        mock_svc.create = AsyncMock(return_value=policy_version)

        with patch(
            "src.api.admin.routes.policies._build_service", return_value=mock_svc
        ):
            resp = client_as_admin.post(
                "/v1/policies",
                json={
                    "name": "acl",
                    "version": "1.0.0",
                    "description": "",
                    "rego_body": _VALID_REGO,
                },
            )

        assert resp.status_code == 201
        mock_svc.create.assert_awaited_once()
        call_kwargs = mock_svc.create.call_args
        assert call_kwargs.kwargs["author"] == _AUTHOR

    def test_create_returns_409_on_duplicate(
        self, client_as_admin: TestClient
    ) -> None:
        """AC-2 — 409 when (name, version) already exists."""
        mock_svc = AsyncMock()
        mock_svc.create = AsyncMock(side_effect=IntegrityError("dup", {}, None))

        with patch(
            "src.api.admin.routes.policies._build_service", return_value=mock_svc
        ):
            resp = client_as_admin.post(
                "/v1/policies",
                json={
                    "name": "acl",
                    "version": "1.0.0",
                    "description": "",
                    "rego_body": _VALID_REGO,
                },
            )

        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /v1/policies/{id}/activate — AC-3, AC-6
# ---------------------------------------------------------------------------


class TestActivatePolicy:
    def test_activate_returns_200_with_bundle_push_ok(
        self, client_as_admin: TestClient
    ) -> None:
        """AC-3 — 200 with bundle_push_ok=true."""
        activate_resp = _make_activate_response(bundle_push_ok=True)
        mock_svc = AsyncMock()
        mock_svc.activate = AsyncMock(return_value=activate_resp)

        with patch(
            "src.api.admin.routes.policies._build_service", return_value=mock_svc
        ):
            resp = client_as_admin.post(f"/v1/policies/{_POLICY_ID}/activate")

        assert resp.status_code == 200
        assert resp.json()["bundle_push_ok"] is True
        assert resp.json()["activated_version"] == "1.0.0"

    def test_activate_returns_404_when_policy_not_found(
        self, client_as_admin: TestClient
    ) -> None:
        mock_svc = AsyncMock()
        mock_svc.activate = AsyncMock(side_effect=PolicyNotFoundError("not found"))

        with patch(
            "src.api.admin.routes.policies._build_service", return_value=mock_svc
        ):
            resp = client_as_admin.post(f"/v1/policies/{_POLICY_ID}/activate")

        assert resp.status_code == 404

    def test_activate_returns_409_when_already_active(
        self, client_as_admin: TestClient
    ) -> None:
        mock_svc = AsyncMock()
        mock_svc.activate = AsyncMock(
            side_effect=PolicyAlreadyActiveError("already active")
        )

        with patch(
            "src.api.admin.routes.policies._build_service", return_value=mock_svc
        ):
            resp = client_as_admin.post(f"/v1/policies/{_POLICY_ID}/activate")

        assert resp.status_code == 409

    def test_activate_returns_422_on_invalid_rego(
        self, client_as_admin: TestClient
    ) -> None:
        """AC-6 — 422 with errors list when Rego is syntactically invalid."""
        mock_svc = AsyncMock()
        mock_svc.activate = AsyncMock(
            side_effect=RegoValidationError(["syntax error at line 3"])
        )

        with patch(
            "src.api.admin.routes.policies._build_service", return_value=mock_svc
        ):
            resp = client_as_admin.post(f"/v1/policies/{_POLICY_ID}/activate")

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["message"] == "Rego policy failed syntax validation."
        assert "syntax error at line 3" in detail["errors"]


# ---------------------------------------------------------------------------
# POST /v1/policies/{id}/rollback?version=N — AC-4
# ---------------------------------------------------------------------------


class TestRollbackPolicy:
    def test_rollback_returns_200(
        self, client_as_admin: TestClient, mock_session: AsyncMock
    ) -> None:
        """AC-4 — 200 with RollbackResponse on success."""
        rollback_resp = _make_rollback_response()
        mock_svc = AsyncMock()
        mock_svc.rollback = AsyncMock(return_value=rollback_resp)

        record = MagicMock()
        record.policy_group = "acl"

        mock_repo = AsyncMock(spec=PolicyRepository)
        mock_repo.get_by_id = AsyncMock(return_value=record)

        with (
            patch(
                "src.api.admin.routes.policies._build_service", return_value=mock_svc
            ),
            patch(
                "src.api.admin.routes.policies.PolicyRepository",
                return_value=mock_repo,
            ),
        ):
            resp = client_as_admin.post(
                f"/v1/policies/{_POLICY_ID}/rollback?version=0.9.0"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["restored_version"] == "0.9.0"
        assert body["previous_active"] == "1.0.0"

    def test_rollback_returns_404_when_policy_id_not_found(
        self, client_as_admin: TestClient, mock_session: AsyncMock
    ) -> None:
        """AC-4 — 404 when policy_id record does not exist."""
        mock_svc = AsyncMock()

        mock_repo = AsyncMock(spec=PolicyRepository)
        mock_repo.get_by_id = AsyncMock(return_value=None)

        with (
            patch(
                "src.api.admin.routes.policies._build_service", return_value=mock_svc
            ),
            patch(
                "src.api.admin.routes.policies.PolicyRepository",
                return_value=mock_repo,
            ),
        ):
            resp = client_as_admin.post(
                f"/v1/policies/{_POLICY_ID}/rollback?version=0.9.0"
            )

        assert resp.status_code == 404

    def test_rollback_returns_404_when_target_version_not_found(
        self, client_as_admin: TestClient, mock_session: AsyncMock
    ) -> None:
        """AC-4 — 404 when target version string does not exist in the group."""
        mock_svc = AsyncMock()
        mock_svc.rollback = AsyncMock(
            side_effect=PolicyVersionNotFoundError("version '0.5.0' not found")
        )

        record = MagicMock()
        record.policy_group = "acl"

        mock_repo = AsyncMock(spec=PolicyRepository)
        mock_repo.get_by_id = AsyncMock(return_value=record)

        with (
            patch(
                "src.api.admin.routes.policies._build_service", return_value=mock_svc
            ),
            patch(
                "src.api.admin.routes.policies.PolicyRepository",
                return_value=mock_repo,
            ),
        ):
            resp = client_as_admin.post(
                f"/v1/policies/{_POLICY_ID}/rollback?version=0.5.0"
            )

        assert resp.status_code == 404
        assert "0.5.0" in resp.json()["detail"]

    def test_rollback_returns_422_on_invalid_rego(
        self, client_as_admin: TestClient, mock_session: AsyncMock
    ) -> None:
        mock_svc = AsyncMock()
        mock_svc.rollback = AsyncMock(
            side_effect=RegoValidationError(["compile error"])
        )

        record = MagicMock()
        record.policy_group = "acl"

        mock_repo = AsyncMock(spec=PolicyRepository)
        mock_repo.get_by_id = AsyncMock(return_value=record)

        with (
            patch(
                "src.api.admin.routes.policies._build_service", return_value=mock_svc
            ),
            patch(
                "src.api.admin.routes.policies.PolicyRepository",
                return_value=mock_repo,
            ),
        ):
            resp = client_as_admin.post(
                f"/v1/policies/{_POLICY_ID}/rollback?version=0.9.0"
            )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "rollback target" in detail["message"]
        assert "compile error" in detail["errors"]

    def test_rollback_requires_version_query_param(
        self, client_as_admin: TestClient
    ) -> None:
        """Missing `version` query param should yield 422 validation error."""
        resp = client_as_admin.post(f"/v1/policies/{_POLICY_ID}/rollback")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TASK-US033-05 — AC-1 / AC-6 HTTP-level integration tests
# ---------------------------------------------------------------------------

_US033_VALID_REGO = (
    "package contextiq.authz\n\ndefault allow = false\n\nallow {\n"
    '    input.user_roles[_] == "developer"\n}\n'
)
_US033_INVALID_REGO = "package contextiq.authz\nallow { syntax error here }"
_US033_POLICY_NAME = "contextiq_policies"
_US033_POLICY_VERSION = "1.0.0"
_US033_ADMIN_AUTHOR = "user-sub-abc123"


class TestUS03305AcHttp:
    def test_create_policy_stores_required_fields(
        self, client_as_admin: TestClient
    ) -> None:
        """AC-1: name, description, version, rego_body accepted and persisted."""
        policy_version = _make_policy_version(
            policy_group=_US033_POLICY_NAME,
            version=_US033_POLICY_VERSION,
            status=PolicyStatus.DRAFT,
            author=_US033_ADMIN_AUTHOR,
        )
        mock_svc = AsyncMock()
        mock_svc.create = AsyncMock(return_value=policy_version)

        with patch(
            "src.api.admin.routes.policies._build_service", return_value=mock_svc
        ):
            resp = client_as_admin.post(
                "/v1/policies",
                json={
                    "name": _US033_POLICY_NAME,
                    "description": "Default allow policy",
                    "version": _US033_POLICY_VERSION,
                    "rego_body": _US033_VALID_REGO,
                },
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["policy_group"] == _US033_POLICY_NAME
        assert body["version"] == _US033_POLICY_VERSION
        assert body["status"] == "draft"
        assert body["author"] == _US033_ADMIN_AUTHOR

    def test_activate_invalid_rego_returns_422(
        self, client_as_admin: TestClient
    ) -> None:
        """AC-6: OPA parse error surfaces as HTTP 422 with non-empty errors list."""
        mock_svc = AsyncMock()
        mock_svc.activate = AsyncMock(
            side_effect=RegoValidationError(
                [
                    "1 error occurred: rego_parse_error: unexpected token 'error'"
                ]
            )
        )

        with patch(
            "src.api.admin.routes.policies._build_service", return_value=mock_svc
        ):
            resp = client_as_admin.post(f"/v1/policies/{_POLICY_ID}/activate")

        assert resp.status_code == 422
        body = resp.json()
        assert "errors" in body["detail"]
        assert len(body["detail"]["errors"]) > 0
        assert any(
            "parse" in e.lower() or "error" in e.lower()
            for e in body["detail"]["errors"]
        )
