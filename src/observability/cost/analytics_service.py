from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from langfuse import Langfuse
from pydantic import BaseModel, ConfigDict

from src.observability.cost.settings import LangfuseProjectSettings

logger = logging.getLogger(__name__)


class DailyCostPoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: date
    cost_usd: float


class ModelCostSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    total_cost_usd: float
    daily_series: list[DailyCostPoint]
    total_tokens: int


class ModelCostAnalyticsService:
    """
    Queries Langfuse for GENERATION observations over the last `days` calendar days
    and aggregates them by model_id and calendar date.
    """

    def __init__(self, settings: LangfuseProjectSettings | None = None) -> None:
        cfg = settings or LangfuseProjectSettings()
        self._langfuse = Langfuse(
            public_key=cfg.public_key,
            secret_key=cfg.secret_key,
            host=cfg.host,
        )

    async def get_model_cost_summary(self, days: int = 30) -> list[ModelCostSummary]:
        start_dt = datetime.now(UTC) - timedelta(days=days)

        observations = self._langfuse.observations(
            type="GENERATION",
            from_start_time=start_dt,
            limit=1000,
        )

        # Aggregate: {model_id: {date: {cost_usd, tokens}}}
        by_model: dict[str, dict[date, dict[str, float | int]]] = defaultdict(
            lambda: defaultdict(lambda: {"cost_usd": 0.0, "tokens": 0})
        )

        for obs in observations.data:
            model_id = obs.model or "unknown"
            obs_date = (obs.start_time or datetime.now(UTC)).date()
            cost_usd = obs.calculated_total_cost or 0.0
            total_tokens = (obs.usage.total_tokens or 0) if obs.usage else 0

            by_model[model_id][obs_date]["cost_usd"] = (
                float(by_model[model_id][obs_date]["cost_usd"]) + cost_usd
            )
            by_model[model_id][obs_date]["tokens"] = (
                int(by_model[model_id][obs_date]["tokens"]) + total_tokens
            )

        all_dates = [start_dt.date() + timedelta(days=i) for i in range(days)]

        summaries: list[ModelCostSummary] = []
        for model_id, date_map in by_model.items():
            daily_series = [
                DailyCostPoint(
                    date=d,
                    cost_usd=float(date_map.get(d, {}).get("cost_usd", 0.0)),
                )
                for d in all_dates
            ]
            total_cost = sum(p.cost_usd for p in daily_series)
            total_tokens = sum(int(v["tokens"]) for v in date_map.values())

            summaries.append(
                ModelCostSummary(
                    model_id=model_id,
                    total_cost_usd=round(total_cost, 4),
                    daily_series=daily_series,
                    total_tokens=total_tokens,
                )
            )

        return sorted(summaries, key=lambda s: s.total_cost_usd, reverse=True)
