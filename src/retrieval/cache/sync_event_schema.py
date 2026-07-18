"""Pydantic schema for the contextiq.source.sync Kafka event.

TASK-US013-05: Defines SourceSyncEvent, the message payload published by
EP-008 whenever a source's document index is refreshed.  The schema is
intentionally minimal — only the fields required for cache invalidation are
modelled here; additional EP-008 fields are silently ignored by Pydantic.
"""
from __future__ import annotations

from pydantic import BaseModel


class SourceSyncEvent(BaseModel):
    event_id: str   # UUID v4
    source_id: str  # e.g. "github", "confluence"
    sync_type: str  # "full" | "incremental"
    timestamp: str  # ISO-8601 UTC
    doc_count: int  # number of documents indexed in this sync
