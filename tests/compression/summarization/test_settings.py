"""Unit tests for SummarizationSettings and module-level singleton (TASK-US017-02)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.compression.summarization.settings import (
    SUMMARIZATION_MAX_OUTPUT_TOKENS,
    SUMMARIZATION_TARGET_RATIO,
    SUMMARIZATION_TOKEN_THRESHOLD,
    SummarizationSettings,
    get_summarization_settings,
)

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


class TestSummarizationSettingsDefaults:
    def test_default_token_threshold(self) -> None:
        settings = SummarizationSettings()
        assert settings.token_threshold == SUMMARIZATION_TOKEN_THRESHOLD

    def test_default_token_threshold_value(self) -> None:
        assert SUMMARIZATION_TOKEN_THRESHOLD == 500

    def test_default_model_name(self) -> None:
        settings = SummarizationSettings()
        assert settings.model_name == "gpt-4o-mini"

    def test_default_target_ratio(self) -> None:
        settings = SummarizationSettings()
        assert settings.target_ratio == pytest.approx(SUMMARIZATION_TARGET_RATIO)

    def test_default_target_ratio_value(self) -> None:
        assert SUMMARIZATION_TARGET_RATIO == pytest.approx(0.40)

    def test_default_max_output_tokens(self) -> None:
        settings = SummarizationSettings()
        assert settings.max_output_tokens == SUMMARIZATION_MAX_OUTPUT_TOKENS

    def test_default_max_output_tokens_value(self) -> None:
        assert SUMMARIZATION_MAX_OUTPUT_TOKENS == 400

    def test_default_max_concurrent(self) -> None:
        settings = SummarizationSettings()
        assert settings.max_concurrent == 10

    def test_default_langfuse_enabled(self) -> None:
        settings = SummarizationSettings()
        assert settings.langfuse_enabled is True


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------


class TestSummarizationSettingsEnvOverride:
    def test_token_threshold_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUMMARIZATION_TOKEN_THRESHOLD", "300")
        settings = SummarizationSettings()
        assert settings.token_threshold == 300

    def test_model_name_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUMMARIZATION_MODEL_NAME", "gpt-4o")
        settings = SummarizationSettings()
        assert settings.model_name == "gpt-4o"

    def test_target_ratio_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUMMARIZATION_TARGET_RATIO", "0.50")
        settings = SummarizationSettings()
        assert settings.target_ratio == pytest.approx(0.50)

    def test_max_output_tokens_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUMMARIZATION_MAX_OUTPUT_TOKENS", "200")
        settings = SummarizationSettings()
        assert settings.max_output_tokens == 200

    def test_max_concurrent_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUMMARIZATION_MAX_CONCURRENT", "5")
        settings = SummarizationSettings()
        assert settings.max_concurrent == 5

    def test_langfuse_enabled_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUMMARIZATION_LANGFUSE_ENABLED", "false")
        settings = SummarizationSettings()
        assert settings.langfuse_enabled is False


# ---------------------------------------------------------------------------
# Boundary validation — token_threshold
# ---------------------------------------------------------------------------


class TestSummarizationSettingsTokenThresholdBoundaries:
    def test_token_threshold_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            SummarizationSettings(token_threshold=0)

    def test_token_threshold_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            SummarizationSettings(token_threshold=-1)

    def test_token_threshold_one_accepted(self) -> None:
        settings = SummarizationSettings(token_threshold=1)
        assert settings.token_threshold == 1


# ---------------------------------------------------------------------------
# Boundary validation — target_ratio
# ---------------------------------------------------------------------------


class TestSummarizationSettingsTargetRatioBoundaries:
    def test_target_ratio_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            SummarizationSettings(target_ratio=0.0)

    def test_target_ratio_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            SummarizationSettings(target_ratio=1.0)

    def test_target_ratio_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            SummarizationSettings(target_ratio=1.1)

    def test_target_ratio_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            SummarizationSettings(target_ratio=-0.1)

    def test_target_ratio_near_zero_accepted(self) -> None:
        settings = SummarizationSettings(target_ratio=0.01)
        assert settings.target_ratio == pytest.approx(0.01)

    def test_target_ratio_near_one_accepted(self) -> None:
        settings = SummarizationSettings(target_ratio=0.99)
        assert settings.target_ratio == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# Boundary validation — max_output_tokens
# ---------------------------------------------------------------------------


class TestSummarizationSettingsMaxOutputTokensBoundaries:
    def test_max_output_tokens_below_minimum_raises(self) -> None:
        with pytest.raises(ValidationError):
            SummarizationSettings(max_output_tokens=49)

    def test_max_output_tokens_minimum_accepted(self) -> None:
        settings = SummarizationSettings(max_output_tokens=50)
        assert settings.max_output_tokens == 50


# ---------------------------------------------------------------------------
# Boundary validation — max_concurrent
# ---------------------------------------------------------------------------


class TestSummarizationSettingsMaxConcurrentBoundaries:
    def test_max_concurrent_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            SummarizationSettings(max_concurrent=0)

    def test_max_concurrent_one_accepted(self) -> None:
        settings = SummarizationSettings(max_concurrent=1)
        assert settings.max_concurrent == 1


# ---------------------------------------------------------------------------
# Singleton behaviour
# ---------------------------------------------------------------------------


class TestGetSummarizationSettings:
    def test_returns_same_instance(self) -> None:
        import src.compression.summarization.settings as settings_module

        # Reset singleton to ensure clean state
        settings_module._settings = None

        first = get_summarization_settings()
        second = get_summarization_settings()
        assert first is second

    def test_singleton_is_settings_instance(self) -> None:
        import src.compression.summarization.settings as settings_module

        settings_module._settings = None
        instance = get_summarization_settings()
        assert isinstance(instance, SummarizationSettings)
