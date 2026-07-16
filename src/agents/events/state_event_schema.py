"""Immutable Pydantic schema for agent state transition events.

Published to the ``contextiq.state.events`` Kafka topic on every
``AgentState`` status transition and consumed by the Replay Service (EP-011).
"""
from __future__ import annotations

from pydantic import BaseModel


class StateTransitionEvent(BaseModel):
    event_id: str       # UUID v4 — unique per event
    request_id: str     # thread_id / LangGraph checkpoint key
    user_id: str
    from_status: str    # previous ExecutionStatus value
    to_status: str      # new ExecutionStatus value
    node_name: str      # LangGraph node that triggered the transition
    timestamp: str      # ISO-8601 UTC
    duration_ms: int    # time spent in the completed node
    error: str | None = None
    execution_plan_snapshot: dict | None = None  # serialised ExecutionPlan; set only by intent_agent

    model_config = {"frozen": True}
