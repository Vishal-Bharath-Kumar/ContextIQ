"""
Entry-point auto-discovery for ContextIQ connectors.

TASK-US021-02: Entry-Point Auto-Discovery and ConnectorRegistry.

Third-party connector packages register themselves under the
``contextiq.connectors`` entry-point group in their ``pyproject.toml``.
This module loads those entry points at startup so the platform discovers
connectors without any core code changes.
"""
from __future__ import annotations

import importlib.metadata
import inspect
import logging

from src.connector_sdk.base import BaseConnector

_logger = logging.getLogger(__name__)


def discover_connectors() -> dict[str, type[BaseConnector]]:
    """Load all entry points under the ``contextiq.connectors`` group.

    Returns
    -------
    dict[str, type[BaseConnector]]
        Mapping of ``{connector_id: ConnectorClass}`` for every valid entry
        point.  Invalid entries (import error, wrong type) are logged and
        skipped — the function never raises.
    """
    discovered: dict[str, type[BaseConnector]] = {}
    eps = importlib.metadata.entry_points(group="contextiq.connectors")

    for ep in eps:
        try:
            cls = ep.load()
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "connector_discovery_failed",
                extra={"entry_point": ep.name, "error": str(exc)},
            )
            continue

        if not (inspect.isclass(cls) and issubclass(cls, BaseConnector)):
            _logger.warning(
                "connector_not_a_baseconnector",
                extra={"entry_point": ep.name, "cls": repr(cls)},
            )
            continue

        discovered[ep.name] = cls

    return discovered
