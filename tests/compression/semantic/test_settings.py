"""Unit tests for SemanticDedupSettings and module-level singleton (TASK-US016-01)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.compression.semantic.settings import (
    SEMANTIC_EMBED_BATCH_SIZE,
    SEMANTIC_SIMILARITY_THRESHOLD,
    SemanticDedupSettings,
    get_semantic_dedup_settings,
)

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


class TestSemanticDedupSettingsDefaults:
    def test_default_threshold(self) -> None:
        settings = SemanticDedupSettings()
        assert settings.threshold == SEMANTIC_SIMILARITY_THRESHOLD

    def test_default_threshold_value(self) -> None:
        assert SEMANTIC_SIMILARITY_THRESHOLD == 0.92

    def test_default_batch_size(self) -> None:
        settings = SemanticDedupSettings()
        assert settings.batch_size == SEMANTIC_EMBED_BATCH_SIZE

    def test_default_batch_size_value(self) -> None:
        assert SEMANTIC_EMBED_BATCH_SIZE == 64


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------


class TestSemanticDedupSettingsEnvOverride:
    def test_threshold_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEMANTIC_DEDUP_THRESHOLD", "0.85")
        settings = SemanticDedupSettings()
        assert settings.threshold == pytest.approx(0.85)

    def test_batch_size_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEMANTIC_DEDUP_BATCH_SIZE", "32")
        settings = SemanticDedupSettings()
        assert settings.batch_size == 32

    def test_threshold_override_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEMANTIC_DEDUP_THRESHOLD", "1.0")
        settings = SemanticDedupSettings()
        assert settings.threshold == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Boundary validation — threshold
# ---------------------------------------------------------------------------


class TestSemanticDedupSettingsThresholdBoundaries:
    def test_threshold_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            SemanticDedupSettings(threshold=0.0)

    def test_threshold_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            SemanticDedupSettings(threshold=1.01)

    def test_threshold_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            SemanticDedupSettings(threshold=-0.1)

    def test_threshold_at_boundary_low(self) -> None:
        settings = SemanticDedupSettings(threshold=0.01)
        assert settings.threshold == pytest.approx(0.01)

    def test_threshold_at_boundary_high(self) -> None:
        settings = SemanticDedupSettings(threshold=1.0)
        assert settings.threshold == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Boundary validation — batch_size
# ---------------------------------------------------------------------------


class TestSemanticDedupSettingsBatchSizeBoundaries:
    def test_batch_size_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            SemanticDedupSettings(batch_size=0)

    def test_batch_size_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            SemanticDedupSettings(batch_size=-1)

    def test_batch_size_one_accepted(self) -> None:
        settings = SemanticDedupSettings(batch_size=1)
        assert settings.batch_size == 1


# ---------------------------------------------------------------------------
# Singleton behaviour
# ---------------------------------------------------------------------------


class TestGetSemanticDedupSettings:
    def test_returns_same_instance(self) -> None:
        import src.compression.semantic.settings as settings_module

        # Reset singleton to ensure clean state
        settings_module._settings = None

        first = get_semantic_dedup_settings()
        second = get_semantic_dedup_settings()
        assert first is second

    def test_singleton_is_settings_instance(self) -> None:
        import src.compression.semantic.settings as settings_module

        settings_module._settings = None
        instance = get_semantic_dedup_settings()
        assert isinstance(instance, SemanticDedupSettings)
