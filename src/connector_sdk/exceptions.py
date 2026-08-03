"""
Custom exceptions for the ContextIQ connector SDK.

TASK-US021-01: BaseConnector Abstract Class and Core SDK Data Models.
"""
from __future__ import annotations


class ConnectorAuthError(Exception):
    """Raised by authenticate() when credentials cannot be obtained or validated."""
