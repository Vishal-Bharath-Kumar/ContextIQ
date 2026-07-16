"""
ConnectorQuery — the input contract for all connector fetch() calls.

TASK-US021-01: BaseConnector Abstract Class and Core SDK Data Models.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ConnectorQuery(BaseModel):
    """Immutable query sent to a connector's fetch() method."""

    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=1, max_length=2000)
    filters: dict[str, str] = Field(default_factory=dict)
    max_results: int = Field(default=50, gt=0, le=500)
