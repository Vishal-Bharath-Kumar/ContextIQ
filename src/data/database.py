"""
Async database engine and session factories.

Two engines are provided:
  - _primary_engine()  — writable; points at PgBouncer → PostgreSQL primary
  - _replica_engine()  — read-only advisory; points at PgBouncer → PostgreSQL read replicas

AC-6: audit log queries and cost analytics use the replica engine to keep
reporting traffic off the primary write path.

PgBouncer transaction mode constraints (TASK-US050-04):
  - LISTEN/NOTIFY is not supported; use a direct PostgreSQL connection for pub/sub.
  - Prepared statements must be disabled (statement_cache_size=0 in connect_args).

URL sources (rendered by Vault Agent into container environment):
  DATABASE_URL       — PgBouncer → primary   (postgresql+asyncpg://...)
  DATABASE_READ_URL  — PgBouncer → replicas  (falls back to DATABASE_URL in dev/test)
"""
from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


@lru_cache(maxsize=1)
def _primary_engine() -> AsyncEngine:
    url = os.environ["DATABASE_URL"]    # PgBouncer → PostgreSQL primary
    # Allow local dev to disable TLS if Postgres wasn't initialized with SSL.
    # Default keeps existing behaviour (require TLS) unless explicitly set to
    # a falsy value such as "0"/"false"/"no"/"off" in the environment.
    ssl_required = os.environ.get("DATABASE_REQUIRE_SSL", "true").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    connect_args = {"statement_cache_size": 0}
    if ssl_required:
        connect_args["ssl"] = "require"

    return create_async_engine(
        url,
        pool_size=5,         # intentionally small per pod; PgBouncer aggregates across pods
        max_overflow=10,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@lru_cache(maxsize=1)
def _replica_engine() -> AsyncEngine:
    # AC-6: falls back to DATABASE_URL when replicas are not configured (dev/test)
    url = os.environ.get("DATABASE_READ_URL", os.environ["DATABASE_URL"])
    ssl_required = os.environ.get("DATABASE_REQUIRE_SSL", "true").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    connect_args = {"statement_cache_size": 0}
    if ssl_required:
        connect_args["ssl"] = "require"

    return create_async_engine(
        url,
        pool_size=5,
        max_overflow=20,    # replicas may serve more concurrent reporting reads
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def primary_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the primary (writable) engine."""
    return async_sessionmaker(_primary_engine(), expire_on_commit=False, autoflush=False)


def replica_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the read-replica engine (AC-6)."""
    return async_sessionmaker(_replica_engine(), expire_on_commit=False, autoflush=False)
