from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from src.observability.cost.recorder import LLMCostRecorder
from src.observability.cost.schemas import CompressionRecord, LLMCallRecord
from src.observability.cost.settings import LangfuseProjectSettings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
_REQ_ID = uuid.uuid4()


@pytest.fixture()
def llm_record() -> LLMCallRecord:
    return LLMCallRecord(
        request_id=_REQ_ID,
        tenant_id="tenant-1",
        model_id="gpt-4o",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.005,
        user_id="user-abc",
        team_id="team-xyz",
        intent_type="query",
        timestamp=_NOW,
    )


@pytest.fixture()
def compression_record() -> CompressionRecord:
    return CompressionRecord(
        request_id=_REQ_ID,
        tenant_id="tenant-1",
        user_id="user-abc",
        team_id="team-xyz",
        intent_type="query",
        timestamp=_NOW,
        tokens_before_compression=1000,
        tokens_after_compression=750,
    )


@pytest.fixture()
def mock_langfuse() -> Generator[MagicMock, None, None]:
    with patch("src.observability.cost.recorder.Langfuse") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


@pytest.fixture()
def recorder(mock_langfuse: MagicMock) -> LLMCostRecorder:
    settings = LangfuseProjectSettings(
        public_key="pk-test",
        secret_key="sk-test",
        host="http://localhost:3000",
    )
    return LLMCostRecorder(settings=settings)


# ---------------------------------------------------------------------------
# LLMCallRecord schema tests
# ---------------------------------------------------------------------------


class TestLLMCallRecord:
    def test_all_six_ac1_fields_present(self, llm_record: LLMCallRecord) -> None:
        """AC-1: LLMCallRecord contains all six required fields."""
        assert llm_record.model_id == "gpt-4o"
        assert llm_record.prompt_tokens == 100
        assert llm_record.completion_tokens == 50
        assert llm_record.cost_usd == 0.005
        assert llm_record.user_id == "user-abc"
        assert llm_record.team_id == "team-xyz"

    def test_frozen_model_rejects_mutation(self, llm_record: LLMCallRecord) -> None:
        with pytest.raises(ValidationError):
            llm_record.model_id = "changed"  # type: ignore[misc]

    def test_prompt_tokens_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            LLMCallRecord(
                request_id=uuid.uuid4(),
                tenant_id="t",
                model_id="gpt-4o",
                prompt_tokens=-1,
                completion_tokens=0,
                cost_usd=0.0,
                user_id="u",
                team_id="g",
                timestamp=_NOW,
            )

    def test_cost_usd_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            LLMCallRecord(
                request_id=uuid.uuid4(),
                tenant_id="t",
                model_id="gpt-4o",
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd=-0.01,
                user_id="u",
                team_id="g",
                timestamp=_NOW,
            )

    def test_default_intent_type(self) -> None:
        record = LLMCallRecord(
            request_id=uuid.uuid4(),
            tenant_id="t",
            model_id="gpt-4o",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.001,
            user_id="u",
            team_id="g",
            timestamp=_NOW,
        )
        assert record.intent_type == "unknown"


# ---------------------------------------------------------------------------
# CompressionRecord schema tests
# ---------------------------------------------------------------------------


class TestCompressionRecord:
    def test_savings_tokens(self, compression_record: CompressionRecord) -> None:
        """AC-2: savings_tokens = before - after."""
        assert compression_record.savings_tokens == 250

    def test_savings_pct(self, compression_record: CompressionRecord) -> None:
        """AC-2: savings_pct = 25.0% for 1000→750."""
        assert compression_record.savings_pct == 25.0

    def test_savings_pct_zero_division(self) -> None:
        """AC: savings_pct returns 0.0 when tokens_before_compression == 0."""
        record = CompressionRecord(
            request_id=uuid.uuid4(),
            tenant_id="t",
            user_id="u",
            team_id="g",
            timestamp=_NOW,
            tokens_before_compression=0,
            tokens_after_compression=0,
        )
        assert record.savings_pct == 0.0

    def test_savings_tokens_never_negative(self) -> None:
        """savings_tokens is clamped to 0 if after > before."""
        record = CompressionRecord(
            request_id=uuid.uuid4(),
            tenant_id="t",
            user_id="u",
            team_id="g",
            timestamp=_NOW,
            tokens_before_compression=100,
            tokens_after_compression=200,
        )
        assert record.savings_tokens == 0

    def test_frozen_model_rejects_mutation(self, compression_record: CompressionRecord) -> None:
        with pytest.raises(ValidationError):
            compression_record.user_id = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# LLMCostRecorder tests
# ---------------------------------------------------------------------------


class TestLLMCostRecorder:
    def test_record_llm_call_invokes_langfuse_generation(
        self, recorder: LLMCostRecorder, mock_langfuse: MagicMock, llm_record: LLMCallRecord
    ) -> None:
        """AC-1: record_llm_call calls langfuse.generation()."""
        recorder.record_llm_call(llm_record)
        mock_langfuse.generation.assert_called_once()

    def test_record_llm_call_passes_all_six_ac1_fields_in_metadata(
        self, recorder: LLMCostRecorder, mock_langfuse: MagicMock, llm_record: LLMCallRecord
    ) -> None:
        """AC-1, AC-4: All six AC-1 fields present in metadata kwarg."""
        recorder.record_llm_call(llm_record)
        _, kwargs = mock_langfuse.generation.call_args
        meta = kwargs["metadata"]
        assert meta["model_id"] == "gpt-4o"
        assert meta["prompt_tokens"] == 100
        assert meta["completion_tokens"] == 50
        assert meta["cost_usd"] == 0.005
        assert meta["user_id"] == "user-abc"
        assert meta["team_id"] == "team-xyz"

    def test_record_llm_call_does_not_raise_on_exception(
        self, recorder: LLMCostRecorder, mock_langfuse: MagicMock, llm_record: LLMCallRecord
    ) -> None:
        """Fire-and-forget safety: exceptions are swallowed."""
        mock_langfuse.generation.side_effect = RuntimeError("network error")
        recorder.record_llm_call(llm_record)  # must not raise

    def test_record_compression_invokes_langfuse_event(
        self,
        recorder: LLMCostRecorder,
        mock_langfuse: MagicMock,
        compression_record: CompressionRecord,
    ) -> None:
        """AC-2: record_compression calls langfuse.event()."""
        recorder.record_compression(compression_record)
        mock_langfuse.event.assert_called_once()

    def test_record_compression_passes_ac2_fields(
        self,
        recorder: LLMCostRecorder,
        mock_langfuse: MagicMock,
        compression_record: CompressionRecord,
    ) -> None:
        """AC-2: tokens_before/after_compression present in metadata."""
        recorder.record_compression(compression_record)
        _, kwargs = mock_langfuse.event.call_args
        meta = kwargs["metadata"]
        assert meta["tokens_before_compression"] == 1000
        assert meta["tokens_after_compression"] == 750

    def test_record_compression_does_not_raise_on_exception(
        self,
        recorder: LLMCostRecorder,
        mock_langfuse: MagicMock,
        compression_record: CompressionRecord,
    ) -> None:
        """Fire-and-forget safety: exceptions are swallowed."""
        mock_langfuse.event.side_effect = RuntimeError("network error")
        recorder.record_compression(compression_record)  # must not raise

    def test_flush_delegates_to_langfuse(
        self, recorder: LLMCostRecorder, mock_langfuse: MagicMock
    ) -> None:
        """flush() calls langfuse.flush()."""
        recorder.flush()
        mock_langfuse.flush.assert_called_once()


# ---------------------------------------------------------------------------
# LangfuseProjectSettings tests
# ---------------------------------------------------------------------------


class TestLangfuseProjectSettings:
    def test_default_retention_months(self) -> None:
        settings = LangfuseProjectSettings(public_key="pk", secret_key="sk")
        assert settings.required_retention_months == 12

    def test_default_host(self) -> None:
        settings = LangfuseProjectSettings(public_key="pk", secret_key="sk")
        assert settings.host == "https://cloud.langfuse.com"

    def test_env_prefix_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "env-pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "env-sk")
        monkeypatch.setenv("LANGFUSE_HOST", "http://self-hosted.example.com")
        settings = LangfuseProjectSettings()
        assert settings.public_key == "env-pk"
        assert settings.secret_key == "env-sk"
        assert settings.host == "http://self-hosted.example.com"
