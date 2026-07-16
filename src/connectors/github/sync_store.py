"""
ConnectorSyncStore — reads and writes the last_sync_at cursor for a connector.

TASK-US022-04: GitHubConnector.sync() — Incremental Sync with `since` Parameter.

Table: connector_sync_state (connector_id VARCHAR PK, last_sync_at TIMESTAMPTZ).
Created by EP-DATA-001 migration.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ConnectorSyncStore:
    """
    Reads and writes the last_sync_at timestamp for a connector instance.

    Args:
        session: An active SQLAlchemy async session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_last_sync_at(self, connector_id: str) -> datetime | None:
        """
        Return the most recent sync timestamp for *connector_id*, or ``None``
        when no prior sync has been recorded.
        """
        row = await self._session.execute(
            text(
                "SELECT last_sync_at FROM connector_sync_state"
                " WHERE connector_id = :id"
            ),
            {"id": connector_id},
        )
        result = row.fetchone()
        return result[0] if result else None

    async def set_last_sync_at(self, connector_id: str, synced_at: datetime) -> None:
        """
        Upsert the sync timestamp for *connector_id*.

        Uses ``ON CONFLICT … DO UPDATE`` so this is safe for both first-time
        writes and subsequent updates.
        """
        await self._session.execute(
            text(
                """
                INSERT INTO connector_sync_state (connector_id, last_sync_at)
                VALUES (:id, :ts)
                ON CONFLICT (connector_id)
                DO UPDATE SET last_sync_at = EXCLUDED.last_sync_at
                """
            ),
            {"id": connector_id, "ts": synced_at},
        )
        await self._session.commit()
