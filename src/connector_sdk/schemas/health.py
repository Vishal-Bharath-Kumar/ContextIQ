"""
HealthStatus — returned by a connector's health_check() method.

TASK-US021-01: BaseConnector Abstract Class and Core SDK Data Models.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HealthStatus(BaseModel):
    """Result of a connector health probe."""

    model_config = ConfigDict(frozen=True)

    healthy: bool
    message: str = Field(max_length=200)    # human-readable; logged by health poller
    checked_at: datetime
