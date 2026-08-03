"""LiteLLM callback integration for Langfuse.

LiteLLM automatically integrates with Langfuse when the following
environment variables are set:
- LANGFUSE_PUBLIC_KEY
- LANGFUSE_SECRET_KEY
- LANGFUSE_HOST or LANGFUSE_BASE_URL

This module provides helper functions to ensure Langfuse is enabled
in LiteLLM and to manage the integration.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def enable_litellm_langfuse() -> bool:
    """
    Enable Langfuse integration in LiteLLM.
    
    LiteLLM automatically sends traces to Langfuse when the environment
    variables are set. This function verifies the configuration.
    
    Returns:
        True if Langfuse is configured, False otherwise.
    """
    has_public_key = bool(os.getenv("LANGFUSE_PUBLIC_KEY"))
    has_secret_key = bool(os.getenv("LANGFUSE_SECRET_KEY"))
    has_host = bool(os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL"))
    
    if has_public_key and has_secret_key and has_host:
        logger.info("LiteLLM Langfuse integration enabled via environment variables")
        return True
    else:
        logger.debug(
            "LiteLLM Langfuse integration not configured. "
            "Set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_HOST."
        )
        return False


def get_litellm_callback() -> Optional[str]:
    """
    Get the Langfuse callback identifier for LiteLLM.
    
    Returns:
        "langfuse" if configured, None otherwise.
        
    Usage:
        callback = get_litellm_callback()
        callbacks = [callback] if callback else []
        response = await litellm.acompletion(..., callbacks=callbacks)
    
    Note: LiteLLM accepts "langfuse" as a string callback name and
    automatically handles the integration when environment variables are set.
    """
    if enable_litellm_langfuse():
        return "langfuse"
    return None
