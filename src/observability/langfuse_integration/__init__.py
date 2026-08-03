"""
Langfuse observability integration for ContextIQ.

Provides comprehensive LLM tracing with:
- Automatic LiteLLM integration via callbacks
- Function-level tracing with @observe decorator
- Trace metadata (session_id, user_id, tags)
- Agent graph visualization
- Cost and token tracking
"""

from src.observability.langfuse_integration.setup import (
    get_langfuse,
    setup_langfuse,
    teardown_langfuse,
)
from src.observability.langfuse_integration.decorators import (
    observe_llm,
    update_current_trace,
    update_current_observation,
)
from src.observability.langfuse_integration.callbacks import get_litellm_callback

__all__ = [
    "get_langfuse",
    "setup_langfuse",
    "teardown_langfuse",
    "observe_llm",
    "update_current_trace",
    "update_current_observation",
    "get_litellm_callback",
]
