"""Unit tests for Replay Explorer API routes — TASK-US035-02.

Covers all acceptance criteria:
  AC-1  — GET /v1/traces filters by user_id and date range
  AC-2  — GET /v1/traces/{id} response contains timeline with steps
  AC-3  — GET /v1/traces/{id} response contains all six detail fields
  AC-4  — 403 for developer role; 200 for auditor (case-insensitive) and admin
  AC-5  — Endpoints resolve via mocked service (SLA enforced by service layer)
  AC-6  — GET /v1/traces/{id}/export returns Content-Disposition attachment
  404   — GET /v1/traces/{id} returns 404 for unknown request_id
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from src.api.admin.dependencies import require_auditor_or_admin  # noqa: F401
from src.audit.replay.schemas import (
    TimelineStep,
    TraceDetailResponse,
    TraceListItem,
    TraceListResponse,
)
from src.audit.replay.service import TraceDetailService, TraceNotFoundInIndexError
from src.audit.trace.schemas import CompressionDelta, GovernanceDecisionSummary
from src.auth.dependencies import decode_jwt_claims
from src.auth.middleware import JWTAuthMiddleware
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.data.dependencies import get_db, get_redis_client
from src.gateway.schemas.auth_types import JWTClaims
from src.main import app

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_REQUEST_ID = uuid.uuid4()
_UNKNOWN_ID = uuid.uuid4()
_NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=UTC)
_USER_ID = "user-auditor-001"

_TIMELINE_STEP = TimelineStep(step_number=1, node="retrieval_node", eval_ms=42.0)

_DETAIL_RESPONSE = TraceDetailResponse(
    request_id=_REQUEST_ID,
    user_id=_USER_ID,
    timestamp=_NOW,
    latency_ms=120.5,
    intent_classification="question_answering",
    retrieved_sources=[],
    compression_delta=CompressionDelta(
        tokens_before=500, tokens_after=300, chunks_before=10, chunks_after=6
    ),
    governance_decisions=GovernanceDecisionSummary(
        findings_count=0,
        redacted_count=0,
        opa_denied_count=0,
        opa_bundle_version="v1.0",
        governance_blocked=False,
    ),
    model_selected="gpt-4o",
    response_summary="A helpful answer.",
    timeline=[_TIMELINE_STEP],
)

_LIST_RESPONSE = TraceListResponse(
    items=[
        TraceListItem(
            request_id=_REQUEST_ID,
            user_id=_USER_ID,
            timestamp=_NOW,
            intent="question_answering",
            model_selected="gpt-4o",
            governance_blocked=False,
            opa_denied_count=0,
            object_key="traces/2026/07/17/test.json",
        )
    ],
    total=1,
    limit=50,
    offset=0,
)

_RAW_JSON = b'{"request_id": "' + str(_REQUEST_ID).encode() + b'"}'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def bypass_jwt_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace JWTAuthMiddleware.dispatch with a pass-through for all tests."""

    async def _passthrough(
        self: object,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        return await call_next(request)

    monkeypatch.setattr(JWTAuthMiddleware, "dispatch", _passthrough)


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_redis() -> MagicMock:
    return MagicMock()


def _make_client(claims: JWTClaims, mock_session: AsyncMock, mock_redis: MagicMock) -> TestClient:
    app.dependency_overrides[decode_jwt_claims] = lambda: claims
    app.dependency_overrides[get_db] = lambda: mock_session
    app.dependency_overrides[get_redis_client] = lambda: mock_redis
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auditor_claims() -> JWTClaims:
    return make_test_claims(PlatformRole.AUDITOR, sub=_USER_ID)


@pytest.fixture
def admin_claims() -> JWTClaims:
    return make_test_claims(PlatformRole.ADMIN, sub=_USER_ID)


@pytest.fixture
def developer_claims() -> JWTClaims:
    return make_test_claims(PlatformRole.DEVELOPER, sub="dev-user-001")


@pytest.fixture
def client_as_auditor(
    auditor_claims: JWTClaims, mock_session: AsyncMock, mock_redis: MagicMock
) -> TestClient:
    client = _make_client(auditor_claims, mock_session, mock_redis)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client_as_admin(
    admin_claims: JWTClaims, mock_session: AsyncMock, mock_redis: MagicMock
) -> TestClient:
    client = _make_client(admin_claims, mock_session, mock_redis)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client_as_developer(
    developer_claims: JWTClaims, mock_session: AsyncMock, mock_redis: MagicMock
) -> TestClient:
    client = _make_client(developer_claims, mock_session, mock_redis)
    yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC-4 RBAC tests
# ---------------------------------------------------------------------------


class TestRBAC:
    def test_search_traces_returns_403_for_developer(
        self, client_as_developer: TestClient
    ) -> None:
        """AC-4: developer role must receive 403 on GET /v1/traces."""
        resp = client_as_developer.get("/v1/traces")
        assert resp.status_code == 403

    def test_search_traces_returns_200_for_auditor(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-4: auditor role must receive 200 on GET /v1/traces."""
        with _patch_service_search(_LIST_RESPONSE):
            resp = client_as_auditor.get("/v1/traces")
        assert resp.status_code == 200

    def test_search_traces_returns_200_for_admin(
        self, client_as_admin: TestClient
    ) -> None:
        """AC-4: admin role must receive 200 on GET /v1/traces."""
        with _patch_service_search(_LIST_RESPONSE):
            resp = client_as_admin.get("/v1/traces")
        assert resp.status_code == 200

    def test_get_detail_returns_403_for_developer(
        self, client_as_developer: TestClient
    ) -> None:
        """AC-4: developer role must receive 403 on GET /v1/traces/{id}."""
        resp = client_as_developer.get(f"/v1/traces/{_REQUEST_ID}")
        assert resp.status_code == 403

    def test_export_returns_403_for_developer(
        self, client_as_developer: TestClient
    ) -> None:
        """AC-4: developer role must receive 403 on export endpoint."""
        resp = client_as_developer.get(f"/v1/traces/{_REQUEST_ID}/export")
        assert resp.status_code == 403

    def test_rbac_case_insensitive_auditor_role(
        self, mock_session: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """AC-4: AUDITOR (uppercase) in realm_access must be accepted."""
        import time

        now = int(time.time())
        upper_claims = JWTClaims(
            sub=_USER_ID,
            iss="https://keycloak.test/realms/contextiq",
            exp=now + 3600,
            iat=now,
            email="test@example.com",
            email_verified=True,
            preferred_username="testuser",
            realm_access={"roles": ["AUDITOR"]},  # uppercase
            resource_access={},
        )
        client = _make_client(upper_claims, mock_session, mock_redis)
        try:
            with _patch_service_search(_LIST_RESPONSE):
                resp = client.get("/v1/traces")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC-1 search filter tests
# ---------------------------------------------------------------------------


class TestSearchTraces:
    def test_returns_list_response_structure(
        self, client_as_auditor: TestClient
    ) -> None:
        """GET /v1/traces returns TraceListResponse with items, total, limit, offset."""
        with _patch_service_search(_LIST_RESPONSE):
            resp = client_as_auditor.get("/v1/traces")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] == 1

    def test_user_id_filter_is_passed_to_service(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-1: user_id query param is forwarded to the service layer."""
        with _patch_service_search(_LIST_RESPONSE) as mock_search:
            resp = client_as_auditor.get("/v1/traces?user_id=alice")
        assert resp.status_code == 200
        called_query = mock_search.call_args[0][1]
        assert called_query.user_id == "alice"

    def test_date_range_filter_is_passed_to_service(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-1: from/to timestamp params are parsed and forwarded."""
        from_ts = "2026-01-01T00:00:00"
        to_ts = "2026-12-31T23:59:59"
        with _patch_service_search(_LIST_RESPONSE) as mock_search:
            resp = client_as_auditor.get(f"/v1/traces?from={from_ts}&to={to_ts}")
        assert resp.status_code == 200
        called_query = mock_search.call_args[0][1]
        assert called_query.from_timestamp is not None
        assert called_query.to_timestamp is not None

    def test_intent_filter_is_passed_to_service(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-1: intent query param is forwarded to the service layer."""
        with _patch_service_search(_LIST_RESPONSE) as mock_search:
            resp = client_as_auditor.get("/v1/traces?intent=technical_support")
        assert resp.status_code == 200
        called_query = mock_search.call_args[0][1]
        assert called_query.intent == "technical_support"

    def test_governance_blocked_filter_is_passed_to_service(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-1: governance_blocked query param is forwarded to the service layer."""
        with _patch_service_search(_LIST_RESPONSE) as mock_search:
            resp = client_as_auditor.get("/v1/traces?governance_blocked=true")
        assert resp.status_code == 200
        called_query = mock_search.call_args[0][1]
        assert called_query.governance_blocked is True

    def test_model_selected_filter_is_passed_to_service(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-1: model_selected query param is forwarded to the service layer."""
        with _patch_service_search(_LIST_RESPONSE) as mock_search:
            resp = client_as_auditor.get("/v1/traces?model_selected=gpt-4o")
        assert resp.status_code == 200
        called_query = mock_search.call_args[0][1]
        assert called_query.model_selected == "gpt-4o"

    def test_search_defaults_to_default_tenant_when_request_has_no_tenant(
        self, client_as_auditor: TestClient
    ) -> None:
        """Replay search should use the local single-tenant default when no tenant context exists."""
        with _patch_service_search(_LIST_RESPONSE) as mock_search:
            resp = client_as_auditor.get("/v1/traces")
        assert resp.status_code == 200
        called_tenant = mock_search.call_args[0][0]
        assert called_tenant == "default"


# ---------------------------------------------------------------------------
# AC-2, AC-3 detail view tests
# ---------------------------------------------------------------------------


class TestGetTraceDetail:
    def test_returns_timeline_with_steps(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-2: response body contains timeline with at least one step."""
        with _patch_service_detail(_DETAIL_RESPONSE):
            resp = client_as_auditor.get(f"/v1/traces/{_REQUEST_ID}")
        assert resp.status_code == 200
        body = resp.json()
        assert "timeline" in body
        assert len(body["timeline"]) >= 1

    def test_timeline_steps_are_in_ascending_order(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-2: timeline step_numbers are in ascending order."""
        multi_step_detail = _DETAIL_RESPONSE.model_copy(
            update={
                "timeline": [
                    TimelineStep(step_number=1, node="retrieval_node", eval_ms=45.0),
                    TimelineStep(step_number=2, node="compression_node", eval_ms=12.0),
                    TimelineStep(step_number=3, node="governance_node", eval_ms=8.5),
                ]
            }
        )
        with _patch_service_detail(multi_step_detail):
            resp = client_as_auditor.get(f"/v1/traces/{_REQUEST_ID}")
        assert resp.status_code == 200
        steps = resp.json()["timeline"]
        step_numbers = [s["step_number"] for s in steps]
        assert step_numbers == sorted(step_numbers)
        assert steps[0]["node"] == "retrieval_node"

    def test_returns_all_six_ac3_fields(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-3: all six required detail fields are present in the response."""
        with _patch_service_detail(_DETAIL_RESPONSE):
            resp = client_as_auditor.get(f"/v1/traces/{_REQUEST_ID}")
        assert resp.status_code == 200
        body = resp.json()
        for field in (
            "intent_classification",
            "retrieved_sources",
            "compression_delta",
            "governance_decisions",
            "model_selected",
            "response_summary",
        ):
            assert field in body, f"AC-3 field '{field}' missing from response"

    def test_returns_404_for_unknown_id(
        self, client_as_auditor: TestClient
    ) -> None:
        """GET /v1/traces/{id} returns 404 when trace is not found."""
        with _patch_service_detail_not_found():
            resp = client_as_auditor.get(f"/v1/traces/{_UNKNOWN_ID}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC-6 export tests
# ---------------------------------------------------------------------------


class TestExportTrace:
    def test_returns_attachment_content_disposition(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-6: Content-Disposition header is present and set to attachment."""
        with _patch_service_raw_json(_RAW_JSON):
            resp = client_as_auditor.get(f"/v1/traces/{_REQUEST_ID}/export")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_returns_json_content_type(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-6: Media type is application/json."""
        with _patch_service_raw_json(_RAW_JSON):
            resp = client_as_auditor.get(f"/v1/traces/{_REQUEST_ID}/export")
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("content-type", "")

    def test_export_returns_404_for_unknown_id(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-6 / 404: export endpoint raises 404 for unknown trace id."""
        with _patch_service_raw_json_not_found():
            resp = client_as_auditor.get(f"/v1/traces/{_UNKNOWN_ID}/export")
        assert resp.status_code == 404

    def test_filename_contains_request_id(
        self, client_as_auditor: TestClient
    ) -> None:
        """AC-6: filename in Content-Disposition includes the request_id."""
        with _patch_service_raw_json(_RAW_JSON):
            resp = client_as_auditor.get(f"/v1/traces/{_REQUEST_ID}/export")
        assert str(_REQUEST_ID) in resp.headers.get("content-disposition", "")


# ---------------------------------------------------------------------------
# Patch context managers for TraceDetailService
# ---------------------------------------------------------------------------


@contextmanager
def _patch_service_search(return_value: TraceListResponse) -> MagicMock:
    svc = MagicMock(spec=TraceDetailService)
    svc.search = AsyncMock(return_value=return_value)
    with patch(
        "src.api.admin.routes.replay._build_service", return_value=svc
    ):
        yield svc.search


@contextmanager
def _patch_service_detail(return_value: TraceDetailResponse) -> MagicMock:
    svc = MagicMock(spec=TraceDetailService)
    svc.get_detail = AsyncMock(return_value=return_value)
    with patch("src.api.admin.routes.replay._build_service", return_value=svc):
        yield svc.get_detail


@contextmanager
def _patch_service_detail_not_found() -> None:
    svc = MagicMock(spec=TraceDetailService)
    svc.get_detail = AsyncMock(side_effect=TraceNotFoundInIndexError("not found"))
    with patch("src.api.admin.routes.replay._build_service", return_value=svc):
        yield


@contextmanager
def _patch_service_raw_json(return_value: bytes) -> None:
    svc = MagicMock(spec=TraceDetailService)
    svc.get_raw_json = AsyncMock(return_value=return_value)
    with patch("src.api.admin.routes.replay._build_service", return_value=svc):
        yield


@contextmanager
def _patch_service_raw_json_not_found() -> None:
    svc = MagicMock(spec=TraceDetailService)
    svc.get_raw_json = AsyncMock(side_effect=TraceNotFoundInIndexError("not found"))
    with patch("src.api.admin.routes.replay._build_service", return_value=svc):
        yield
