"""
Business logic for the tool registry lifecycle.

TASK-US002-02: create, read, update, soft-delete tool definitions and emit
Redis pub/sub events on every mutation so the cache layer (TASK-US002-03)
can invalidate its entries within the 100 ms SLA.

Pub/sub channel: contextiq:tool_registry:changed
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.registry.models.tool import Tool, ToolStatus
from src.registry.repositories.tool_repository import ToolRepository

logger = logging.getLogger(__name__)

_PUBSUB_CHANNEL = "contextiq:tool_registry:changed"


class DuplicateToolError(Exception):
    """Raised when a tool with the same name already exists."""


class ToolNotFoundError(Exception):
    """Raised when no tool matches the requested name."""


class ToolRegistryService:
    def __init__(self, session: AsyncSession, redis_client: Any) -> None:
        self._repo = ToolRepository(session)
        self._session = session
        self._redis = redis_client

    async def create_tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
        version: str = "1.0.0",
    ) -> Tool:
        existing = await self._repo.get_by_name(name)
        if existing is not None:
            raise DuplicateToolError(f"Tool '{name}' already exists")

        tool = Tool(
            name=name,
            description=description,
            input_schema=input_schema,
            status=ToolStatus.ACTIVE.value,
            version=version,
        )
        created = await self._repo.create(tool)
        await self._session.commit()
        await self._publish_changed(created.name, "created")
        return created

    async def get_tool(self, name: str) -> Tool:
        tool = await self._repo.get_by_name(name)
        if tool is None:
            raise ToolNotFoundError(f"Tool '{name}' not found")
        return tool

    async def list_tools(self, status: ToolStatus | None = None) -> Sequence[Tool]:
        return await self._repo.list_all(status=status)

    async def update_tool(
        self,
        name: str,
        description: str | None = None,
        input_schema: dict | None = None,
        status: str | None = None,
        version: str | None = None,
    ) -> Tool:
        tool = await self._repo.get_by_name(name)
        if tool is None:
            raise ToolNotFoundError(f"Tool '{name}' not found")

        if description is not None:
            tool.description = description
        if input_schema is not None:
            tool.input_schema = input_schema
        if status is not None:
            tool.status = status
        if version is not None:
            tool.version = version
        tool.updated_at = datetime.now(tz=timezone.utc)

        updated = await self._repo.update(tool)
        await self._session.commit()
        await self._publish_changed(updated.name, "updated")
        return updated

    async def delete_tool(self, name: str) -> Tool:
        """Soft-delete: sets status = 'inactive'."""
        return await self.update_tool(name, status=ToolStatus.INACTIVE.value)

    async def hard_delete_tool(self, name: str) -> Tool:
        """Hard-delete: permanently removes the tool from the database."""
        tool = await self._repo.get_by_name(name)
        if tool is None:
            raise ToolNotFoundError(f"Tool '{name}' not found")

        # Delete from database
        await self._repo.delete(tool)
        await self._session.commit()
        await self._publish_changed(tool.name, "deleted")
        return tool

    async def _publish_changed(self, tool_name: str, action: str) -> None:
        payload = json.dumps({"tool": tool_name, "action": action})
        try:
            await self._redis.publish(_PUBSUB_CHANNEL, payload)
        except Exception:
            logger.warning(
                "Failed to publish tool_registry change event",
                extra={"tool": tool_name, "action": action},
            )
