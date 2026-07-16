"""Per-connector timeout configuration — TASK-US007-02.

Provides per-source timeout overrides on top of a global default that can be
overridden via the ``CONNECTOR_TIMEOUT_SECONDS`` environment variable.

Usage::

    from src.agents.retrieval.timeout_config import get_connector_timeout

    timeout = get_connector_timeout("github:my-org/repo")  # returns 8.0
    timeout = get_connector_timeout("unknown:source")      # returns DEFAULT_TIMEOUT
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Global default — overridable via env var
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT: float = float(os.environ.get("CONNECTOR_TIMEOUT_SECONDS", "5.0"))

# ---------------------------------------------------------------------------
# Per connector-type overrides
# ---------------------------------------------------------------------------

CONNECTOR_TIMEOUT_OVERRIDES: dict[str, float] = {
    "github": 8.0,      # GitHub API can be slow for large repos
    "confluence": 5.0,
    "jira": 5.0,
    "grafana": 3.0,     # Metrics API should be fast
}


def get_connector_timeout(source_id: str) -> float:
    """Return the effective timeout (seconds) for *source_id*.

    Extracts the connector type from *source_id* by splitting on the first
    colon (e.g. ``"github:org/repo"`` → ``"github"``).  Falls back to
    :data:`DEFAULT_TIMEOUT` when no override exists for the connector type.

    Args:
        source_id: Connector registry key in the form ``<type>:<path>``.

    Returns:
        Timeout in seconds as a :class:`float`.
    """
    connector_type = source_id.split(":")[0]
    return CONNECTOR_TIMEOUT_OVERRIDES.get(connector_type, DEFAULT_TIMEOUT)
