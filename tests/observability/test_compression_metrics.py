"""Unit tests for CompressionMetricsRecorder and Prometheus metric wiring.

Coverage:
  - AC-2: tokens_before and tokens_after are recorded per request
  - AC-3: contextiq_compression_savings_ratio histogram is observed correctly
  - Edge case: zero tokens_before suppresses ratio observation (no NaN/Inf)
  - AC-6: all four Prometheus label dimensions are present in each sample
  - LLMCostRecorder.record_compression() is called once per execution
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.observability.cost.compression_metrics import CompressionMetricsRecorder
from src.observability.cost.schemas import CompressionRecord

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)
_REQ_ID = uuid.uuid4()

_BASE_LABELS = {
    "service": "contextiq-api",
    "team_id": "team-alpha",
    "tenant_id": "tenant-001",
    "intent_type": "query",
}


@pytest.fixture()
def cost_recorder_mock() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def recorder(cost_recorder_mock: MagicMock) -> CompressionMetricsRecorder:
    return CompressionMetricsRecorder(cost_recorder=cost_recorder_mock)


def _make_record(
    *,
    tokens_before: int = 1000,
    tokens_after: int = 700,
    team_id: str = "team-alpha",
    tenant_id: str = "tenant-001",
    intent_type: str = "query",
) -> CompressionRecord:
    return CompressionRecord(
        request_id=_REQ_ID,
        tenant_id=tenant_id,
        user_id="user-abc",
        team_id=team_id,
        intent_type=intent_type,
        timestamp=_NOW,
        tokens_before_compression=tokens_before,
        tokens_after_compression=tokens_after,
    )


# ---------------------------------------------------------------------------
# AC-2: token counters
# ---------------------------------------------------------------------------


class TestTokenCounters:
    def test_tokens_before_counter_incremented(
        self, recorder: CompressionMetricsRecorder
    ) -> None:
        """contextiq_compression_tokens_total{stage="before"} increases by tokens_before."""
        rec = _make_record(tokens_before=800, tokens_after=500, team_id="team-b1")

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_tokens_total"
        ) as mock_counter:
            mock_child = MagicMock()
            mock_counter.labels.return_value = mock_child

            recorder.record(rec)

        mock_counter.labels.assert_any_call(
            service="contextiq-api",
            team_id="team-b1",
            tenant_id="tenant-001",
            intent_type="query",
            stage="before",
        )
        assert mock_child.inc.call_count == 2

    def test_tokens_after_counter_incremented(
        self, recorder: CompressionMetricsRecorder
    ) -> None:
        """contextiq_compression_tokens_total{stage="after"} increases by tokens_after."""
        rec = _make_record(tokens_before=900, tokens_after=450, team_id="team-b2")

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_tokens_total"
        ) as mock_counter:
            mock_child = MagicMock()
            mock_counter.labels.return_value = mock_child

            recorder.record(rec)

        mock_counter.labels.assert_any_call(
            service="contextiq-api",
            team_id="team-b2",
            tenant_id="tenant-001",
            intent_type="query",
            stage="after",
        )

    def test_savings_tokens_counter_incremented(
        self, recorder: CompressionMetricsRecorder
    ) -> None:
        """contextiq_compression_savings_tokens_total increases by savings_tokens."""
        rec = _make_record(tokens_before=1000, tokens_after=600, team_id="team-b3")
        expected_savings = rec.savings_tokens  # 400

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_savings_tokens_total"
        ) as mock_savings:
            mock_child = MagicMock()
            mock_savings.labels.return_value = mock_child

            recorder.record(rec)

        mock_savings.labels.assert_called_once_with(
            service="contextiq-api",
            team_id="team-b3",
            tenant_id="tenant-001",
            intent_type="query",
        )
        mock_child.inc.assert_called_once_with(expected_savings)

    def test_before_inc_value(self, recorder: CompressionMetricsRecorder) -> None:
        """inc() for stage='before' is called with the exact tokens_before value."""
        tokens_before = 1234
        rec = _make_record(tokens_before=tokens_before, tokens_after=800, team_id="team-b4")

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_tokens_total"
        ) as mock_counter:
            before_child = MagicMock()
            after_child = MagicMock()

            def labels_side_effect(**kwargs: object) -> MagicMock:
                return before_child if kwargs.get("stage") == "before" else after_child

            mock_counter.labels.side_effect = labels_side_effect

            recorder.record(rec)

        before_child.inc.assert_called_once_with(tokens_before)

    def test_after_inc_value(self, recorder: CompressionMetricsRecorder) -> None:
        """inc() for stage='after' is called with the exact tokens_after value."""
        tokens_after = 567
        rec = _make_record(tokens_before=1200, tokens_after=tokens_after, team_id="team-b5")

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_tokens_total"
        ) as mock_counter:
            before_child = MagicMock()
            after_child = MagicMock()

            def labels_side_effect(**kwargs: object) -> MagicMock:
                return before_child if kwargs.get("stage") == "before" else after_child

            mock_counter.labels.side_effect = labels_side_effect

            recorder.record(rec)

        after_child.inc.assert_called_once_with(tokens_after)


# ---------------------------------------------------------------------------
# AC-3: compression ratio histogram
# ---------------------------------------------------------------------------


class TestRatioHistogram:
    def test_ratio_observed_when_tokens_before_nonzero(
        self, recorder: CompressionMetricsRecorder
    ) -> None:
        """contextiq_compression_savings_ratio observes a value in [0, 1]."""
        rec = _make_record(tokens_before=1000, tokens_after=700, team_id="team-r1")
        expected_ratio = 300 / 1000  # 0.3

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_savings_ratio"
        ) as mock_hist:
            mock_child = MagicMock()
            mock_hist.labels.return_value = mock_child

            recorder.record(rec)

        mock_hist.labels.assert_called_once_with(
            service="contextiq-api",
            team_id="team-r1",
            tenant_id="tenant-001",
            intent_type="query",
        )
        mock_child.observe.assert_called_once_with(pytest.approx(expected_ratio))

    def test_ratio_is_zero_when_fully_compressed(
        self, recorder: CompressionMetricsRecorder
    ) -> None:
        """ratio = 0.0 when tokens_after equals tokens_before (no savings)."""
        rec = _make_record(tokens_before=500, tokens_after=500, team_id="team-r2")

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_savings_ratio"
        ) as mock_hist:
            mock_child = MagicMock()
            mock_hist.labels.return_value = mock_child

            recorder.record(rec)

        mock_child.observe.assert_called_once_with(pytest.approx(0.0))

    def test_ratio_not_observed_when_tokens_before_is_zero(
        self, recorder: CompressionMetricsRecorder
    ) -> None:
        """AC edge-case: tokens_before == 0 must not produce a ratio observation."""
        rec = _make_record(tokens_before=0, tokens_after=0, team_id="team-r3")

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_savings_ratio"
        ) as mock_hist:
            mock_child = MagicMock()
            mock_hist.labels.return_value = mock_child

            recorder.record(rec)

        mock_child.observe.assert_not_called()

    def test_ratio_bounded_between_zero_and_one(
        self, recorder: CompressionMetricsRecorder
    ) -> None:
        """Ratio is always in [0, 1] even with maximum savings."""
        rec = _make_record(tokens_before=1000, tokens_after=0, team_id="team-r4")

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_savings_ratio"
        ) as mock_hist:
            mock_child = MagicMock()
            mock_hist.labels.return_value = mock_child

            recorder.record(rec)

        observed = mock_child.observe.call_args[0][0]
        assert 0.0 <= observed <= 1.0


# ---------------------------------------------------------------------------
# AC-6: label dimensions
# ---------------------------------------------------------------------------


class TestLabelDimensions:
    def test_all_four_label_dimensions_present_in_tokens_counter(
        self, recorder: CompressionMetricsRecorder
    ) -> None:
        """service, team_id, tenant_id, intent_type all appear in tokens_total calls."""
        rec = _make_record(
            team_id="team-l1",
            tenant_id="tenant-labels",
            intent_type="debugging",
        )

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_tokens_total"
        ) as mock_counter:
            mock_counter.labels.return_value = MagicMock()
            recorder.record(rec)

        for kw_call in mock_counter.labels.call_args_list:
            kwargs = kw_call.kwargs
            assert "service" in kwargs
            assert "team_id" in kwargs
            assert "tenant_id" in kwargs
            assert "intent_type" in kwargs
            assert "stage" in kwargs

    def test_all_four_label_dimensions_present_in_savings_counter(
        self, recorder: CompressionMetricsRecorder
    ) -> None:
        """service, team_id, tenant_id, intent_type all appear in savings_tokens_total."""
        rec = _make_record(team_id="team-l2", tenant_id="tenant-l2", intent_type="code-gen")

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_savings_tokens_total"
        ) as mock_counter:
            mock_counter.labels.return_value = MagicMock()
            recorder.record(rec)

        kwargs = mock_counter.labels.call_args.kwargs
        assert kwargs["service"] == "contextiq-api"
        assert kwargs["team_id"] == "team-l2"
        assert kwargs["tenant_id"] == "tenant-l2"
        assert kwargs["intent_type"] == "code-gen"

    def test_all_four_label_dimensions_present_in_ratio_histogram(
        self, recorder: CompressionMetricsRecorder
    ) -> None:
        """service, team_id, tenant_id, intent_type all appear in savings_ratio."""
        rec = _make_record(team_id="team-l3", tenant_id="tenant-l3", intent_type="incident")

        with patch(
            "src.observability.cost.compression_metrics.contextiq_compression_savings_ratio"
        ) as mock_hist:
            mock_hist.labels.return_value = MagicMock()
            recorder.record(rec)

        kwargs = mock_hist.labels.call_args.kwargs
        assert kwargs["service"] == "contextiq-api"
        assert kwargs["team_id"] == "team-l3"
        assert kwargs["tenant_id"] == "tenant-l3"
        assert kwargs["intent_type"] == "incident"


# ---------------------------------------------------------------------------
# AC-2: LLMCostRecorder.record_compression() called once per execution
# ---------------------------------------------------------------------------


class TestLangfuseIntegration:
    def test_record_compression_called_once(
        self,
        recorder: CompressionMetricsRecorder,
        cost_recorder_mock: MagicMock,
    ) -> None:
        """LLMCostRecorder.record_compression() is invoked exactly once per record() call."""
        rec = _make_record(tokens_before=500, tokens_after=300)

        with (
            patch("src.observability.cost.compression_metrics.contextiq_compression_tokens_total"),
            patch("src.observability.cost.compression_metrics.contextiq_compression_savings_tokens_total"),
            patch("src.observability.cost.compression_metrics.contextiq_compression_savings_ratio"),
        ):
            recorder.record(rec)

        cost_recorder_mock.record_compression.assert_called_once_with(rec)

    def test_record_compression_passes_correct_record(
        self,
        recorder: CompressionMetricsRecorder,
        cost_recorder_mock: MagicMock,
    ) -> None:
        """The CompressionRecord instance passed to record_compression is identical."""
        rec = _make_record(tokens_before=888, tokens_after=444)

        with (
            patch("src.observability.cost.compression_metrics.contextiq_compression_tokens_total"),
            patch("src.observability.cost.compression_metrics.contextiq_compression_savings_tokens_total"),
            patch("src.observability.cost.compression_metrics.contextiq_compression_savings_ratio"),
        ):
            recorder.record(rec)

        passed_rec = cost_recorder_mock.record_compression.call_args[0][0]
        assert passed_rec is rec

    def test_record_compression_called_even_when_tokens_before_is_zero(
        self,
        recorder: CompressionMetricsRecorder,
        cost_recorder_mock: MagicMock,
    ) -> None:
        """Langfuse is always notified regardless of token counts."""
        rec = _make_record(tokens_before=0, tokens_after=0)

        with (
            patch("src.observability.cost.compression_metrics.contextiq_compression_tokens_total"),
            patch("src.observability.cost.compression_metrics.contextiq_compression_savings_tokens_total"),
            patch("src.observability.cost.compression_metrics.contextiq_compression_savings_ratio"),
        ):
            recorder.record(rec)

        cost_recorder_mock.record_compression.assert_called_once()
