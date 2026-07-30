"""Langfuse SDK initialization and lifecycle management."""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.observability.langfuse_integration.settings import LangfuseSettings

logger = logging.getLogger(__name__)

# Module-level Langfuse client instance
_langfuse_client: Any | None = None
_langfuse_settings: Optional[LangfuseSettings] = None


def setup_langfuse(settings: Optional[LangfuseSettings] = None) -> Any | None:
    """
    Initialize Langfuse SDK.
    
    Must be called AFTER environment variables are loaded.
    Follows Langfuse best practice: import and initialize after env vars.
    
    Args:
        settings: Optional LangfuseSettings. If None, loads from environment.
        
    Returns:
        Configured Langfuse client, or None if disabled/not configured.
    """
    global _langfuse_client, _langfuse_settings
    
    if _langfuse_client is not None:
        logger.debug("Langfuse already initialized")
        return _langfuse_client
    
    _langfuse_settings = settings or LangfuseSettings()
    
    if not _langfuse_settings.is_configured:
        logger.warning(
            "Langfuse not configured. Set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, "
            "and LANGFUSE_ENABLED=true to enable tracing."
        )
        return None
    
    try:
        from langfuse import Langfuse  # noqa: PLC0415

        _langfuse_client = Langfuse(
            public_key=_langfuse_settings.public_key,
            secret_key=_langfuse_settings.secret_key,
            host=_langfuse_settings.base_url,
            flush_interval=_langfuse_settings.flush_interval,
            release=_langfuse_settings.release,
            environment=_langfuse_settings.environment,
        )
        
        logger.info(
            "Langfuse initialized: host=%s environment=%s release=%s",
            _langfuse_settings.base_url,
            _langfuse_settings.environment,
            _langfuse_settings.release,
        )
        
        return _langfuse_client
    
    except Exception as e:
        logger.exception("Failed to initialize Langfuse: %s", e)
        return None


def get_langfuse() -> Any | None:
    """
    Get the initialized Langfuse client.
    
    Returns:
        Langfuse client or None if not initialized.
    """
    if _langfuse_client is None:
        logger.warning("Langfuse not initialized. Call setup_langfuse() first.")
    return _langfuse_client


def teardown_langfuse() -> None:
    """
    Flush and cleanup Langfuse SDK.
    
    Should be called during application shutdown to ensure all
    traces are sent before the process exits.
    """
    global _langfuse_client
    
    if _langfuse_client is not None:
        try:
            logger.info("Flushing Langfuse traces...")
            _langfuse_client.flush()
            logger.info("Langfuse flush complete")
        except Exception as e:
            logger.exception("Error flushing Langfuse: %s", e)
        finally:
            _langfuse_client = None
