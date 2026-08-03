"""Tests for on-demand sync endpoints — TASK-US026-04.

Uses httpx.AsyncClient with mocked dependencies; no database connection required.
asyncio.create_task is patched to verify dispatch without executing the background job.

Acceptance criteria covered:
  AC-1  POST /{id}/sync returns HTTP 202 immediately with job_id
  AC-2  POST /{id}/sync with unknown source_id returns HTTP 404
  AC-3  asyncio.create_task dispatched (non-blocking) — verified by patch
  AC-4  GET /{id}/sync/{job_id} returns SyncJobResponse (status may be running)
  AC-5  GET /{id}/sync/{job_id} with wrong source_id returns 404
  AC-5b GET /{id}/sync/{job_id} for nonexistent job returns 404
  AC-6  Non-admin requests return HTTP 403
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth.dependencies import decode_jwt_claims
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.data.dependencies import get_db
from src.knowledge_sources.dependencies import get_knowledge_source_service
from src.knowledge_sources.models.sync_job import SyncJobStatus
from src.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_create_task(coro: object, *, name: str | None = None) -> MagicMock:
    """Replacement for asyncio.create_task that closes the coroutine immediately.

    Prevents 'coroutine was never awaited' RuntimeWarning while still recording
    the call for assertion.
    """
    if hasattr(coro, "close"):
        coro.close()  # type: ignore[union-attr]
    return MagicMock()


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_ADMIN_CLAIMS = make_test_claims(PlatformRole.ADMIN)
_DEVELOPER_CLAIMS = make_test_claims(PlatformRole.DEVELOPER)

_SOURCE_ID = uuid4()
_JOB_ID = uuid4()

_NOW = dt.datetime(2026, 7, 16, 12, 0, 0, tzinfo=dt.UTC)

_SYNC_ROUTE = f"/v1/knowledge-sources/{_SOURCE_ID}/sync"
_JOB_ROUTE = f"/v1/knowledge-sources/{_SOURCE_ID}/sync/{_JOB_ID}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    source_id: object = _SOURCE_ID,
    job_id: object = _JOB_ID,
    job_status: SyncJobStatus = SyncJobStatus.RUNNING,
) -> MagicMock:
    job = MagicMock()
    job.id = job_id
    job.source_id = source_id
    job.status = job_status
    job.attempt_number = 1
    job.is_full_sync = True
    job.started_at = _NOW
    job.completed_at = None
    job.duration_s = None
    job.items_processed = None
    job.items_failed = None
    job.error_message = None
    return job


def _mock_service(source: object = None) -> MagicMock:
    svc = MagicMock()
    svc._repo.get_by_id = AsyncMock(return_value=source)
    return svc


# ---------------------------------------------------------------------------
# AC-1: POST returns 202 with job_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_sync_returns_202() -> None:
    """AC-1: POST /{id}/sync returns 202 immediately with a job_id."""
    job = _make_job()
    svc = _mock_service(source=MagicMock())
    mock_session = AsyncMock()

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        with (
            patch(
                "src.knowledge_sources.routers.knowledge_source_router.SyncJobRepository"
            ) as mock_repo_cls,
            patch("asyncio.create_task", side_effect=_noop_create_task),
        ):
            mock_repo = AsyncMock()
            mock_repo.create.return_value = job
            mock_repo_cls.return_value = mock_repo

            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(_SYNC_ROUTE)

        assert response.status_code == 202
        body = response.json()
        assert body["job_id"] == str(_JOB_ID)
        assert body["message"] == "Sync job queued"
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-2: POST with unknown source returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_sync_unknown_source_returns_404() -> None:
    """AC-2: POST /{id}/sync with unknown source_id returns HTTP 404."""
    svc = _mock_service(source=None)
    mock_session = AsyncMock()

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post(f"/v1/knowledge-sources/{uuid4()}/sync")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-3: asyncio.create_task dispatched (non-blocking)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_sync_dispatches_background_task() -> None:
    """AC-3: asyncio.create_task is called once with the correct task name."""
    job = _make_job()
    svc = _mock_service(source=MagicMock())
    mock_session = AsyncMock()

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_knowledge_source_service] = lambda: svc
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        with (
            patch(
                "src.knowledge_sources.routers.knowledge_source_router.SyncJobRepository"
            ) as mock_repo_cls,
            patch(
                "asyncio.create_task", side_effect=_noop_create_task
            ) as mock_create_task,
        ):
            mock_repo = AsyncMock()
            mock_repo.create.return_value = job
            mock_repo_cls.return_value = mock_repo

            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(_SYNC_ROUTE)

        assert response.status_code == 202
        mock_create_task.assert_called_once()
        _, call_kwargs = mock_create_task.call_args
        assert call_kwargs.get("name") == f"on_demand_sync_{_SOURCE_ID}"
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_knowledge_source_service, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-4: GET returns SyncJobResponse with status running
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sync_job_returns_200() -> None:
    """AC-4: GET /{id}/sync/{job_id} returns 200 with SyncJobResponse."""
    job = _make_job()
    mock_session = AsyncMock()

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        with patch(
            "src.knowledge_sources.routers.knowledge_source_router.SyncJobRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.get.return_value = job
            mock_repo_cls.return_value = mock_repo

            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.get(_JOB_ROUTE)

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(_JOB_ID)
        assert body["source_id"] == str(_SOURCE_ID)
        assert body["status"] == "running"
        assert body["attempt_number"] == 1
        assert body["is_full_sync"] is True
        assert body["completed_at"] is None
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-5: GET with job belonging to different source returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sync_job_wrong_source_returns_404() -> None:
    """AC-5: GET /{id}/sync/{job_id} where job belongs to a different source returns 404."""
    other_source_id = uuid4()
    job = _make_job(source_id=other_source_id)
    mock_session = AsyncMock()

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        with patch(
            "src.knowledge_sources.routers.knowledge_source_router.SyncJobRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.get.return_value = job
            mock_repo_cls.return_value = mock_repo

            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.get(_JOB_ROUTE)

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-5b: GET with nonexistent job returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sync_job_nonexistent_returns_404() -> None:
    """AC-5b: GET /{id}/sync/{job_id} for a nonexistent job returns 404."""
    mock_session = AsyncMock()

    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        with patch(
            "src.knowledge_sources.routers.knowledge_source_router.SyncJobRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.get.return_value = None
            mock_repo_cls.return_value = mock_repo

            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.get(
                    f"/v1/knowledge-sources/{_SOURCE_ID}/sync/{uuid4()}"
                )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AC-6: Non-admin requests return 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_sync_non_admin_returns_403() -> None:
    """AC-6: Non-admin POST /{id}/sync returns HTTP 403."""
    app.dependency_overrides[decode_jwt_claims] = lambda: _DEVELOPER_CLAIMS

    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post(_SYNC_ROUTE)

        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)


@pytest.mark.asyncio
async def test_get_sync_job_non_admin_returns_403() -> None:
    """AC-6: Non-admin GET /{id}/sync/{job_id} returns HTTP 403."""
    app.dependency_overrides[decode_jwt_claims] = lambda: _DEVELOPER_CLAIMS

    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get(_JOB_ROUTE)

        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(decode_jwt_claims, None)
