"""ClarificationNeededResponse schema — TASK-US011-02.

Defines the structured response returned by the MCP Gateway ``tools/call``
handler when the agent pipeline exits via the clarification path.  The payload
is serialised as a ``TextContent`` item (not an MCP error) so that IDE clients
and LLM orchestrators can display the question to the user and route the reply
back through the ``clarification_reply`` tool.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ClarificationNeededResponse(BaseModel):
    type: Literal["clarification_needed"] = "clarification_needed"
    question: str
    original_prompt: str
    session_id: str
    clarification_round: int = 0
