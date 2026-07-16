"""
Async repository for the tool_registry table.

TASK-US002-02: provides all DB operations consumed by ToolRegistryService.
TASK-US002-04: find_active() enforces status filtering at the SQL layer,
               including connector-disabled tools via an outer JOIN.
"""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.connector_config import ConnectorConfig
from src.registry.models.tool import Tool, ToolStatus


class ToolRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_active(self) -> Sequence[Tool]:
        """Return only tools that should appear in the MCP tools/list response.

        Filtering rules (enforced at the SQL layer — no app-side post-filtering):
          1. Tool.status must be 'active'.
          2. If the tool is linked to a connector, that connector must be enabled.
          3. Platform-native tools (connector_id IS NULL) are always included when
             their own status is 'active'.

        Single-statement query — no N+1 reads.
        """
        stmt = (
            select(Tool)
            .join(ConnectorConfig, Tool.connector_id == ConnectorConfig.id, isouter=True)
            .where(
                Tool.status == ToolStatus.ACTIVE.value,
                or_(
                    Tool.connector_id.is_(None),
                    ConnectorConfig.enabled.is_(True),
                ),
            )
            .order_by(Tool.name.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create(self, tool: Tool) -> Tool:
        self._session.add(tool)
        await self._session.flush()
        await self._session.refresh(tool)
        return tool

    async def get_by_name(self, name: str) -> Tool | None:
        result = await self._session.execute(
            select(Tool).where(Tool.name == name)
        )
        return result.scalar_one_or_none()

    async def list_all(self, status: ToolStatus | None = None) -> Sequence[Tool]:
        query = select(Tool)
        if status is not None:
            query = query.where(Tool.status == status.value)
        result = await self._session.execute(query)
        return result.scalars().all()

    async def update(self, tool: Tool) -> Tool:
        await self._session.flush()
        await self._session.refresh(tool)
        return tool
