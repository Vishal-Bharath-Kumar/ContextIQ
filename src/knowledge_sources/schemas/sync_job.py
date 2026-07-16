"""Pydantic schema for sync job status responses — TASK-US026-04."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.knowledge_sources.models.sync_job import SyncJobStatus


class SyncJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:              UUID
    source_id:       UUID
    status:          SyncJobStatus
    attempt_number:  int
    is_full_sync:    bool
    started_at:      datetime
    completed_at:    datetime | None
    duration_s:      float | None
    items_processed: int | None
    items_failed:    int | None
    error_message:   str | None
