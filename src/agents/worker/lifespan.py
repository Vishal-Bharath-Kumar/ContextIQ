"""FastAPI lifespan for the agent worker service — TASK-US026-03.

Starts and stops the ``CronSyncScheduler`` alongside the application.
Extend this file for additional background services; do NOT replace the
existing startup/teardown logic.

Usage
-----
Pass ``lifespan`` to the FastAPI constructor::

    from src.agents.worker.lifespan import lifespan
    app = FastAPI(lifespan=lifespan)
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.knowledge_sources.sync.scheduler import CronSyncScheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage background task lifecycle for the agent worker.

    Expects the FastAPI app to have the following state attributes set before
    the lifespan is entered (typically by the application factory):
      - ``app.state.db_session_factory`` — ``async_sessionmaker[AsyncSession]``
      - ``app.state.connector_registry`` — ``ConnectorRegistry``
    """
    scheduler = CronSyncScheduler(
        session_factory=app.state.db_session_factory,
        registry=app.state.connector_registry,
    )
    scheduler.start()
    app.state.sync_scheduler = scheduler

    yield

    scheduler.stop()
