"""Unit tests for TASK-US009-03 — select_sources() and _validate_source_map().

Coverage targets:
- All 8 intent types return their canonical sources at high confidence
- Fallback is triggered when confidence < 0.6
- Boundary: confidence == 0.6 uses SOURCE_MAP (not fallback)
- _validate_source_map raises ValueError for unknown connector IDs
- _validate_source_map passes when all mapped IDs are registered
- SOURCE_MAP contains exactly 8 keys (all IntentType variants)
"""

from __future__ import annotations

import pytest

from src.agents.schemas.intent import IntentType
from src.agents.source_selector import (
    FALLBACK_SOURCES,
    SOURCE_MAP,
    _validate_source_map,
    select_sources,
)


class TestSourceMap:
    def test_covers_all_eight_intent_types(self) -> None:
        assert set(SOURCE_MAP.keys()) == set(IntentType)

    def test_no_duplicate_sources_per_intent(self) -> None:
        for intent, sources in SOURCE_MAP.items():
            assert len(sources) == len(set(sources)), (
                f"Duplicate source key in SOURCE_MAP[{intent}]: {sources}"
            )


class TestSelectSourcesHighConfidence:
    @pytest.mark.parametrize(
        "intent_type,expected",
        [
            (IntentType.DEBUGGING, ["github", "stackoverflow", "jira"]),
            (IntentType.CODE_GEN, ["github", "confluence"]),
            (IntentType.ARCHITECTURE, ["confluence", "github", "miro"]),
            (IntentType.DOCS, ["confluence", "github"]),
            (IntentType.INCIDENT, ["grafana", "jira", "pagerduty"]),
            (IntentType.METRICS, ["grafana", "datadog"]),
            (IntentType.CODE_REVIEW, ["github"]),
            (IntentType.GENERAL, ["confluence", "github", "stackoverflow"]),
        ],
    )
    def test_returns_canonical_sources(
        self, intent_type: IntentType, expected: list[str]
    ) -> None:
        assert select_sources(intent_type, 0.9) == expected

    def test_incident_at_high_confidence(self) -> None:
        assert select_sources(IntentType.INCIDENT, 0.9) == ["grafana", "jira", "pagerduty"]

    def test_boundary_confidence_uses_source_map(self) -> None:
        """confidence == 0.6 should use SOURCE_MAP, not fallback."""
        result = select_sources(IntentType.CODE_GEN, 0.6)
        assert result == SOURCE_MAP[IntentType.CODE_GEN]


class TestSelectSourcesFallback:
    def test_low_confidence_returns_fallback(self) -> None:
        result = select_sources(IntentType.CODE_GEN, 0.4)
        assert result == FALLBACK_SOURCES

    def test_zero_confidence_returns_fallback(self) -> None:
        assert select_sources(IntentType.GENERAL, 0.0) == FALLBACK_SOURCES

    def test_just_below_threshold_returns_fallback(self) -> None:
        assert select_sources(IntentType.INCIDENT, 0.599) == FALLBACK_SOURCES

    def test_fallback_contains_all_mapped_sources(self) -> None:
        """Every source key in SOURCE_MAP must appear in FALLBACK_SOURCES."""
        all_mapped = {s for sources in SOURCE_MAP.values() for s in sources}
        assert all_mapped.issubset(set(FALLBACK_SOURCES))


class TestValidateSourceMap:
    def test_passes_when_all_mapped_ids_registered(self) -> None:
        all_ids = {s for sources in SOURCE_MAP.values() for s in sources}
        # should not raise
        _validate_source_map(all_ids)

    def test_passes_with_superset_of_registered_ids(self) -> None:
        all_ids = {s for sources in SOURCE_MAP.values() for s in sources}
        _validate_source_map(all_ids | {"extra-connector"})

    def test_raises_for_missing_connector(self) -> None:
        with pytest.raises(ValueError, match="unregistered connectors"):
            _validate_source_map(set())

    def test_raises_names_the_unknown_connector(self) -> None:
        registered = {s for sources in SOURCE_MAP.values() for s in sources} - {"github"}
        with pytest.raises(ValueError, match="github"):
            _validate_source_map(registered)

    def test_passes_with_fallback_sources_set(self) -> None:
        """Calling with set(FALLBACK_SOURCES) should always pass."""
        _validate_source_map(set(FALLBACK_SOURCES))
