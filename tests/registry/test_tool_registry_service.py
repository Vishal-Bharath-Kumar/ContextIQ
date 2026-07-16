"""
Unit tests for ToolRegistryService.

TASK-US002-02 acceptance criteria covered:
  - create_tool succeeds and returns the created Tool
  - create_tool raises DuplicateToolError on name collision (HTTP 409)
  - list_tools with status filter returns only matching tools
  - update_tool with status='inactive' disables the tool
  - delete_tool soft-deletes (status = 'inactive')
  - Redis pub/sub event is published after every mutation
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.registry.models.tool import Tool, ToolStatus
from src.registry.services.tool_registry_service import (
    DuplicateToolError,
    ToolNotFoundError,
    ToolRegistryService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 7, 15, 0, 0, 0, tzinfo=timezone.utc)


def _make_tool(
    name: str = "get_context",
    status: str = ToolStatus.ACTIVE.value,
) -> Tool:
    t = Tool(
        name=name,
        description="Retrieve enterprise context for the given prompt",
        input_schema={"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]},
        status=status,
        version="1.0.0",
    )
    t.id = uuid.uuid4()
    t.created_at = NOW
    t.updated_at = NOW
    return t


def _make_service(
    get_by_name_return: Tool | None = None,
    list_all_return: Sequence[Tool] | None = None,
) -> tuple[ToolRegistryService, MagicMock, AsyncMock]:
    """Return (service, mock_repo, mock_redis)."""
    session = AsyncMock()
    session.commit = AsyncMock()
    redis = AsyncMock()

    mock_repo = MagicMock()
    mock_repo.get_by_name = AsyncMock(return_value=get_by_name_return)
    mock_repo.create = AsyncMock(side_effect=lambda t: t)
    mock_repo.list_all = AsyncMock(return_value=list_all_return or [])
    mock_repo.update = AsyncMock(side_effect=lambda t: t)

    svc = ToolRegistryService(session=session, redis_client=redis)
    svc._repo = mock_repo
    return svc, mock_repo, redis


# ---------------------------------------------------------------------------
# create_tool
# ---------------------------------------------------------------------------


class TestCreateTool:
    @pytest.mark.asyncio
    async def test_creates_and_returns_tool(self) -> None:
        svc, repo, redis = _make_service(get_by_name_return=None)

        tool = await svc.create_tool(
            name="get_context",
            description="desc",
            input_schema={"type": "object"},
        )

        assert tool.name == "get_context"
        assert tool.status == ToolStatus.ACTIVE.value
        repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_duplicate_error_on_existing_name(self) -> None:
        existing = _make_tool(name="get_context")
        svc, _, _ = _make_service(get_by_name_return=existing)

        with pytest.raises(DuplicateToolError):
            await svc.create_tool(
                name="get_context",
                description="desc",
                input_schema={},
            )

    @pytest.mark.asyncio
    async def test_publishes_redis_event_on_create(self) -> None:
        svc, _, redis = _make_service(get_by_name_return=None)

        await svc.create_tool(name="my_tool", description="d", input_schema={})

        redis.publish.assert_awaited_once()
        channel, payload = redis.publish.call_args.args
        assert channel == "contextiq:tool_registry:changed"
        assert "my_tool" in payload


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------


class TestListTools:
    @pytest.mark.asyncio
    async def test_list_active_tools_only(self) -> None:
        active = _make_tool(name="active_tool", status=ToolStatus.ACTIVE.value)
        svc, repo, _ = _make_service(list_all_return=[active])

        result = await svc.list_tools(status=ToolStatus.ACTIVE)

        repo.list_all.assert_awaited_once_with(status=ToolStatus.ACTIVE)
        assert result == [active]

    @pytest.mark.asyncio
    async def test_list_all_tools_when_no_filter(self) -> None:
        tools = [_make_tool("a"), _make_tool("b")]
        svc, repo, _ = _make_service(list_all_return=tools)

        result = await svc.list_tools(status=None)

        repo.list_all.assert_awaited_once_with(status=None)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# update_tool / patch status
# ---------------------------------------------------------------------------


class TestUpdateTool:
    @pytest.mark.asyncio
    async def test_patch_status_to_inactive(self) -> None:
        tool = _make_tool(name="get_context", status=ToolStatus.ACTIVE.value)
        svc, repo, redis = _make_service(get_by_name_return=tool)

        updated = await svc.update_tool(name="get_context", status="inactive")

        assert updated.status == "inactive"
        repo.update.assert_awaited_once()
        redis.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_tool(self) -> None:
        svc, _, _ = _make_service(get_by_name_return=None)

        with pytest.raises(ToolNotFoundError):
            await svc.update_tool(name="nonexistent", status="inactive")

    @pytest.mark.asyncio
    async def test_publishes_redis_event_on_update(self) -> None:
        tool = _make_tool("t")
        svc, _, redis = _make_service(get_by_name_return=tool)

        await svc.update_tool(name="t", description="new desc")

        redis.publish.assert_awaited_once()
        _, payload = redis.publish.call_args.args
        assert '"updated"' in payload


# ---------------------------------------------------------------------------
# delete_tool (soft-delete)
# ---------------------------------------------------------------------------


class TestDeleteTool:
    @pytest.mark.asyncio
    async def test_soft_delete_sets_inactive(self) -> None:
        tool = _make_tool(name="get_context", status=ToolStatus.ACTIVE.value)
        svc, repo, redis = _make_service(get_by_name_return=tool)

        result = await svc.delete_tool(name="get_context")

        assert result.status == ToolStatus.INACTIVE.value
        redis.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_raises_not_found(self) -> None:
        svc, _, _ = _make_service(get_by_name_return=None)

        with pytest.raises(ToolNotFoundError):
            await svc.delete_tool(name="ghost")
