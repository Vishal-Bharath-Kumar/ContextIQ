"""ClarificationReplyInput schema — TASK-US011-04.

Input model for the ``clarification_reply`` MCP tool.  The tool accepts the
user's answer to the clarification question and merges it with the original
prompt before re-entering the LangGraph pipeline.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ClarificationReplyInput(BaseModel):
    session_id: str = Field(description="session_id from ClarificationNeededResponse")
    clarification: str = Field(
        description="User's answer to the clarification question.",
        min_length=1,
        max_length=2_000,
    )
