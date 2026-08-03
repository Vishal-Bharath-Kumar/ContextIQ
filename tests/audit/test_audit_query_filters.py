"""
AC-4: Query filter + cursor pagination tests.

Verifies that GET /v1/audit-log correctly filters by action, actor_user_id,
and that cursor-based pagination returns non-overlapping pages.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.main import app


@pytest.mark.asyncio
async def test_filter_by_action(
    db_session: AsyncSession,
    seed_mixed_audit_rows,
    auditor_auth_header: dict,
) -> None:
    """AC-4: ?action=policy.created returns only policy.created rows."""
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/audit-log?action=policy.created",
            headers=auditor_auth_header,
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) > 0
    assert all(item["action"] == "policy.created" for item in data["items"])


@pytest.mark.asyncio
async def test_filter_by_user(
    db_session: AsyncSession,
    seed_mixed_audit_rows,
    auditor_auth_header: dict,
) -> None:
    """AC-4: ?user=user-001 returns only rows for that actor."""
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/audit-log?user=user-001",
            headers=auditor_auth_header,
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) > 0
    assert all(item["actor_user_id"] == "user-001" for item in data["items"])


@pytest.mark.asyncio
async def test_pagination_cursor(
    db_session: AsyncSession,
    seed_60_audit_rows,
    auditor_auth_header: dict,
) -> None:
    """AC-4: Second page returned via cursor is non-overlapping with first page."""
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        first_resp = await client.get(
            "/v1/audit-log?limit=50",
            headers=auditor_auth_header,
        )
        assert first_resp.status_code == 200
        first = first_resp.json()

        cursor = first["next_cursor"]
        assert cursor is not None, "Expected a next_cursor for 60 rows with limit=50"

        second_resp = await client.get(
            f"/v1/audit-log?limit=50&cursor={cursor}",
            headers=auditor_auth_header,
        )
        assert second_resp.status_code == 200
        second = second_resp.json()

    first_ids  = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids), (
        "Pages must not overlap — cursor-based pagination is broken"
    )
    assert len(first["items"]) == 50
    assert len(second["items"]) == 10   # 60 total − 50 first page
