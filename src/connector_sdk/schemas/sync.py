"""
SyncResult — returned by a connector's sync() method.

TASK-US021-01: BaseConnector Abstract Class and Core SDK Data Models.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SyncResult(BaseModel):
    """Summary of a completed incremental sync operation."""

    model_config = ConfigDict(frozen=True)

    items_processed: int
    items_failed: int
    last_sync_at: datetime
    errors: list[str] = []          # error summaries; no stack traces
