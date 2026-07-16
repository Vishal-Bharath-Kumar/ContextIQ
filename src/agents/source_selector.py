"""Intent-to-source-selection mapper — AIR-006 canonical implementation.

TASK-US009-03: translates an ``IntentType`` into an ordered list of
knowledge-source keys so the Retrieval Agent queries only the relevant
connectors.

Source keys are lowercase strings that match connector IDs registered in
the Connector Registry (EP-002 / TASK-US007-04).  ``_validate_source_map``
is called at startup to catch any SOURCE_MAP entries that reference
connectors not yet registered.
"""

from __future__ import annotations

from src.agents.config import INTENT_CONFIDENCE_THRESHOLD
from src.agents.schemas.intent import IntentType

SOURCE_MAP: dict[IntentType, list[str]] = {
    IntentType.DEBUGGING:    ["github", "stackoverflow", "jira"],
    IntentType.CODE_GEN:     ["github", "confluence"],
    IntentType.ARCHITECTURE: ["confluence", "github", "miro"],
    IntentType.DOCS:         ["confluence", "github"],
    IntentType.INCIDENT:     ["grafana", "jira", "pagerduty"],
    IntentType.METRICS:      ["grafana", "datadog"],
    IntentType.CODE_REVIEW:  ["github"],
    IntentType.GENERAL:      ["confluence", "github", "stackoverflow"],
}

FALLBACK_SOURCES: list[str] = [
    "github", "confluence", "grafana", "jira",
    "stackoverflow", "miro", "pagerduty", "datadog",
]


def select_sources(intent_type: IntentType, confidence: float) -> list[str]:
    """Return ordered source keys for the given intent.

    Falls back to all sources when confidence < 0.6 (US-009 AC-5).
    """
    if confidence < INTENT_CONFIDENCE_THRESHOLD:
        return FALLBACK_SOURCES
    return SOURCE_MAP[intent_type]


def _validate_source_map(registered_ids: set[str]) -> None:
    """Assert that every key in SOURCE_MAP is a registered connector ID.

    Called at application startup to fail fast when SOURCE_MAP references
    a connector that has not been registered yet.

    Args:
        registered_ids: Set of connector IDs currently registered.

    Raises:
        ValueError: when SOURCE_MAP references an unregistered connector.
    """
    all_mapped = {s for sources in SOURCE_MAP.values() for s in sources}
    unknown = all_mapped - registered_ids
    if unknown:
        raise ValueError(f"SOURCE_MAP references unregistered connectors: {unknown}")
