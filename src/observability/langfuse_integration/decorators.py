"""Langfuse decorators for function-level tracing."""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Optional, TypeVar

from src.observability.langfuse_integration.setup import get_langfuse

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def observe_llm(
    *,
    name: Optional[str] = None,
    as_type: Optional[str] = None,
    capture_input: bool = True,
    capture_output: bool = True,
) -> Callable[[F], F]:
    """
    Langfuse observation decorator wrapper with safe fallback.
    
    Decorates functions to create Langfuse traces/spans.
    If Langfuse is not configured, the decorator becomes a no-op.
    
    Args:
        name: Custom name for the observation (defaults to function name)
        as_type: Observation type: "generation", "span", "event", "agent", etc.
        capture_input: Whether to capture function input
        capture_output: Whether to capture function output
        
    Usage:
        @observe_llm(as_type="span", name="context-retrieval")
        async def retrieve_context(query: str) -> Context:
            ...
            
        @observe_llm(as_type="generation")
        async def invoke_llm(messages: list) -> str:
            ...
    
    Best Practices (from Langfuse skill):
    - Use as_type="generation" for LLM calls
    - Use as_type="agent" for subagent executions
    - Use as_type="span" for multi-step operations
    - Use as_type="retriever" for context retrieval
    - Nest operations properly to show hierarchy
    """
    langfuse = get_langfuse()
    
    if langfuse is None:
        # Langfuse not configured - return passthrough decorator
        def passthrough(func: F) -> F:
            return func
        return passthrough
    
    # Try to import the decorator from langfuse (v4.x has it in main module)
    try:
        from langfuse import observe
        
        # Langfuse is configured - use the real decorator
        return observe(
            name=name,
            as_type=as_type,
            capture_input=capture_input,
            capture_output=capture_output,
        )
    except ImportError:
        # Fallback: observe not available in this version
        logger.warning(
            "langfuse.observe not available. "
            "Install langfuse>=2.0 with decorator support. "
            "Using passthrough decorator."
        )
        
        def passthrough(func: F) -> F:
            return func
        return passthrough


def update_current_trace(
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> None:
    """
    Update the current Langfuse trace with metadata.
    
    Args:
        session_id: Session/conversation ID for grouping traces
        user_id: User identifier for filtering
        tags: List of tags for categorization
        metadata: Additional metadata dict
        **kwargs: Other trace attributes
        
    Usage:
        @observe_llm(as_type="span")
        async def handle_request(request: Request):
            update_current_trace(
                session_id=request.session_id,
                user_id=request.user_id,
                tags=["chat", "production"],
                metadata={"intent": request.intent}
            )
            ...
    """
    langfuse = get_langfuse()
    if langfuse is None:
        return
    
    try:
        from langfuse.decorators import langfuse_context
        
        update_params = {}
        
        if session_id is not None:
            update_params["session_id"] = session_id
        
        if user_id is not None:
            update_params["user_id"] = user_id
        
        if tags is not None:
            update_params["tags"] = tags
        
        if metadata is not None:
            update_params["metadata"] = metadata
        
        update_params.update(kwargs)
        
        if update_params:
            langfuse_context.update_current_trace(**update_params)
            
    except (ImportError, Exception) as e:
        logger.debug("Failed to update current trace: %s", e)


def update_current_observation(
    *,
    input: Optional[Any] = None,
    output: Optional[Any] = None,
    metadata: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> None:
    """
    Update the current Langfuse observation (span/generation).
    
    Useful for explicitly setting input when you don't want all function args.
    
    Args:
        input: Explicit input to set (e.g., just user message, not API keys)
        output: Explicit output to set
        metadata: Additional metadata
        **kwargs: Other observation attributes
        
    Usage:
        @observe_llm(as_type="generation")
        async def invoke_model(api_key: str, user_message: str):
            # Only capture user_message as input, not api_key
            update_current_observation(input={"message": user_message})
            ...
    """
    langfuse = get_langfuse()
    if langfuse is None:
        return
    
    try:
        from langfuse.decorators import langfuse_context
        
        update_params = {}
        
        if input is not None:
            update_params["input"] = input
        
        if output is not None:
            update_params["output"] = output
        
        if metadata is not None:
            update_params["metadata"] = metadata
        
        update_params.update(kwargs)
        
        if update_params:
            langfuse_context.update_current_observation(**update_params)
            
    except (ImportError, Exception) as e:
        logger.debug("Failed to update current observation: %s", e)
