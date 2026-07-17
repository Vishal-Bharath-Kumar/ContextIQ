from __future__ import annotations

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.database import primary_session_factory, replica_session_factory
from src.data.redis_client import create_redis_client


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


def get_redis_client() -> aioredis.Redis:
    """FastAPI dependency: returns the shared async Redis client (Sentinel HA)."""
    return create_redis_client()
