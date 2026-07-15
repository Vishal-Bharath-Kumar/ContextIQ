from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.database import primary_session_factory, replica_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: writable session on the PostgreSQL primary node."""
    async with primary_session_factory()() as session:
        yield session


async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency: read-only session on a PostgreSQL read replica.

    AC-6: use for audit log queries and cost analytics — keeps reporting
    traffic off the primary write path.
    """
    async with replica_session_factory()() as session:
        yield session
