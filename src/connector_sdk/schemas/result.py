"""
ConnectorResult and ResultMetadata — the output contract for connector fetch() calls.

TASK-US021-01: BaseConnector Abstract Class and Core SDK Data Models.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ResultMetadata(BaseModel):
    """Auxiliary metadata attached to a single fetched item."""

    model_config = ConfigDict(frozen=True)

    source_url: str | None = None
    author: str | None = None
    last_modified: datetime | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class ConnectorResult(BaseModel):
    """A single item returned by a connector's fetch() method."""

    model_config = ConfigDict(frozen=True)

    source_id: str                  # unique stable identifier for this item
    content: str                    # raw text; chunking happens in EP-008
    metadata: ResultMetadata
    fetched_at: datetime
