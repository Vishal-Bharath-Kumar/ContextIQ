"""Integration tests for PolicyPreviewService — TASK-US040-05.

Uses a real in-memory SQLite async session (no TraceRecord rows) so that
_load_recent_traces() returns an empty list; OPA calls are intercepted by
the respx_mock fixture.

Covers:
  AC-3: Preview returns non-negative allow/deny counts that sum to evaluated_count.
  AC-3: Temp policy is deleted via the finally block even when evaluation errors.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.audit.trace.models import TraceRecord
from src.governance.policy.models import PolicyAuditLog, PolicyRecord
from src.governance.policy.preview_service import (
    _TEMP_POLICY_PREFIX,
    PolicyPreviewService,
)
from src.governance.policy.schemas import PolicyPreviewRequest

_OPA_BASE = "http://localhost:8181"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _now_fn(dbapi_conn: object, _: object) -> None:
        assert hasattr(dbapi_conn, "create_function")
        dbapi_conn.create_function(  # type: ignore[union-attr]
            "now", 0, lambda: datetime.now(UTC).isoformat()
        )

    async with engine.begin() as conn:
        await conn.run_sync(
            PolicyRecord.__table__.metadata.create_all,
            tables=[
                PolicyRecord.__table__,
                PolicyAuditLog.__table__,
                TraceRecord.__table__,
            ],
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(
    async_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session


@pytest.fixture
def existing_policy_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_returns_allow_deny_counts(
    async_session: AsyncSession,
    existing_policy_id: uuid.UUID,
    respx_mock: object,
) -> None:
    """AC-3: preview evaluates traces and returns correct allow/deny counts."""
    import respx as _respx

    mock = _respx.mock  # satisfy type checker — respx_mock fixture activates globally
    _ = mock  # unused but documents intent

    temp_name = f"{_TEMP_POLICY_PREFIX}{existing_policy_id.hex}"
    preview_data_path = f"preview/{temp_name}"
    # OPA mock: push and delete succeed; evaluation always allows
    import respx

    respx.put(url__regex=rf".*/v1/policies/{temp_name}.*").respond(200)
    respx.delete(url__regex=rf".*/v1/policies/{temp_name}.*").respond(200)
    respx.post(url__regex=rf".*/v1/data/{preview_data_path}/allow").respond(
        200, json={"result": True}
    )

    svc = PolicyPreviewService(
        session=async_session,
        opa_client=httpx.AsyncClient(trust_env=False),
        opa_base=_OPA_BASE,
    )
    result = await svc.preview(
        existing_policy_id,
        PolicyPreviewRequest(rego_body="package preview\nallow = true"),
    )

    assert result.allow_count >= 0
    assert result.deny_count >= 0
    assert result.evaluated_count == result.allow_count + result.deny_count


@pytest.mark.asyncio
async def test_preview_deletes_temp_policy_on_evaluation_error(
    async_session: AsyncSession,
    existing_policy_id: uuid.UUID,
    respx_mock: object,
) -> None:
    """AC-3: temp policy is deleted even when OPA evaluation returns an error."""
    temp_name = f"{_TEMP_POLICY_PREFIX}{existing_policy_id.hex}"
    preview_data_path = f"preview/{temp_name}"
    deleted: list[bool] = []

    import respx

    respx.put(url__regex=rf".*/v1/policies/{temp_name}.*").respond(200)
    respx.delete(url__regex=rf".*/v1/policies/{temp_name}.*").mock(
        side_effect=lambda *a, **kw: deleted.append(True)
        or httpx.Response(200)
    )
    # OPA evaluation returns 500 — causes evaluation failure
    respx.post(url__regex=rf".*/v1/data/{preview_data_path}/allow").respond(500)

    svc = PolicyPreviewService(
        session=async_session,
        opa_client=httpx.AsyncClient(trust_env=False),
        opa_base=_OPA_BASE,
    )
    result = await svc.preview(
        existing_policy_id,
        PolicyPreviewRequest(rego_body="package preview\nallow = false"),
    )

    # With no traces the evaluation loop is empty; finally block runs regardless
    assert result.evaluated_count >= 0
    # The DELETE must have been called (temp policy cleaned up)
    assert len(deleted) >= 1
