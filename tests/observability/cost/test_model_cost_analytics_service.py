from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.observability.cost.analytics_service import (
    ModelCostAnalyticsService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Use a date within the rolling 30-day window (15 days ago from now)
_NOW = datetime.now(UTC) - timedelta(days=15)


def _make_obs(
    model: str,
    start_time: datetime,
    cost: float,
    total_tokens: int,
) -> MagicMock:
    obs = MagicMock()
    obs.model = model
    obs.start_time = start_time
    obs.calculated_total_cost = cost
    obs.usage = MagicMock()
    obs.usage.total_tokens = total_tokens
    return obs


def _make_service(observations: list) -> ModelCostAnalyticsService:
    """Return a service whose Langfuse client returns `observations`."""
    mock_response = MagicMock()
    mock_response.data = observations

    mock_langfuse = MagicMock()
    mock_langfuse.observations.return_value = mock_response

    with patch(
        "src.observability.cost.analytics_service.Langfuse",
        return_value=mock_langfuse,
    ):
        svc = ModelCostAnalyticsService()
    svc._langfuse = mock_langfuse
    return svc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_observations_returns_empty_list() -> None:
    svc = _make_service([])
    result = await svc.get_model_cost_summary(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_single_observation_produces_correct_summary() -> None:
    obs = _make_obs(
        model="gpt-4o",
        start_time=_NOW,
        cost=0.005,
        total_tokens=600,
    )
    svc = _make_service([obs])
    result = await svc.get_model_cost_summary(days=30)

    assert len(result) == 1
    summary = result[0]
    assert summary.model_id == "gpt-4o"
    assert summary.total_cost_usd == pytest.approx(0.005, abs=1e-6)
    assert summary.total_tokens == 600


@pytest.mark.asyncio
async def test_daily_series_length_always_equals_days() -> None:
    obs = _make_obs(model="claude-3", start_time=_NOW, cost=0.002, total_tokens=200)
    svc = _make_service([obs])

    for days in (7, 14, 30, 90):
        result = await svc.get_model_cost_summary(days=days)
        assert len(result[0].daily_series) == days


@pytest.mark.asyncio
async def test_missing_days_filled_with_zero() -> None:
    """Days with no observations must produce DailyCostPoint(cost_usd=0.0)."""
    obs = _make_obs(model="gpt-4o", start_time=_NOW, cost=0.010, total_tokens=300)
    svc = _make_service([obs])

    result = await svc.get_model_cost_summary(days=30)
    zero_days = [p for p in result[0].daily_series if p.cost_usd == 0.0]
    assert len(zero_days) == 29  # only 1 of 30 days has a charge


@pytest.mark.asyncio
async def test_sorted_by_total_cost_descending() -> None:
    obs_cheap = _make_obs(model="claude-3-haiku", start_time=_NOW, cost=0.001, total_tokens=100)
    obs_expensive = _make_obs(model="gpt-4o", start_time=_NOW, cost=0.050, total_tokens=500)
    svc = _make_service([obs_cheap, obs_expensive])

    result = await svc.get_model_cost_summary(days=30)
    assert result[0].model_id == "gpt-4o"
    assert result[1].model_id == "claude-3-haiku"


@pytest.mark.asyncio
async def test_multiple_observations_same_model_same_day_aggregated() -> None:
    obs1 = _make_obs(model="gpt-4o", start_time=_NOW, cost=0.010, total_tokens=100)
    obs2 = _make_obs(model="gpt-4o", start_time=_NOW, cost=0.020, total_tokens=200)
    svc = _make_service([obs1, obs2])

    result = await svc.get_model_cost_summary(days=30)
    assert len(result) == 1
    assert result[0].total_cost_usd == pytest.approx(0.030, abs=1e-6)
    assert result[0].total_tokens == 300


@pytest.mark.asyncio
async def test_observation_with_none_model_uses_unknown() -> None:
    obs = _make_obs(model=None, start_time=_NOW, cost=0.005, total_tokens=50)  # type: ignore[arg-type]
    obs.model = None
    svc = _make_service([obs])

    result = await svc.get_model_cost_summary(days=30)
    assert result[0].model_id == "unknown"


@pytest.mark.asyncio
async def test_observation_with_none_cost_treated_as_zero() -> None:
    obs = _make_obs(model="gpt-4o", start_time=_NOW, cost=None, total_tokens=100)  # type: ignore[arg-type]
    obs.calculated_total_cost = None
    svc = _make_service([obs])

    result = await svc.get_model_cost_summary(days=30)
    assert result[0].total_cost_usd == 0.0


@pytest.mark.asyncio
async def test_observation_with_none_usage_treats_tokens_as_zero() -> None:
    obs = _make_obs(model="gpt-4o", start_time=_NOW, cost=0.005, total_tokens=0)
    obs.usage = None
    svc = _make_service([obs])

    result = await svc.get_model_cost_summary(days=30)
    assert result[0].total_tokens == 0


@pytest.mark.asyncio
async def test_total_cost_rounded_to_four_decimal_places() -> None:
    obs = _make_obs(model="gpt-4o", start_time=_NOW, cost=0.00005678, total_tokens=10)
    svc = _make_service([obs])

    result = await svc.get_model_cost_summary(days=30)
    # round(..., 4) → 0.0001
    assert str(result[0].total_cost_usd) == "0.0001"
