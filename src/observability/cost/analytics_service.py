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
        self._configured = bool(cfg.public_key and cfg.secret_key)
        self._langfuse = Langfuse(
            public_key=cfg.public_key,
            secret_key=cfg.secret_key,
            host=cfg.host,
        )

    async def get_model_cost_summary(self, days: int = 30) -> list[ModelCostSummary]:
        # No project credentials configured (e.g. local dev without a Langfuse
        # instance) — the SDK client stays uninitialized and `.api` raises
        # AttributeError on access. Degrade to "no cost data yet" instead of 500ing.
        if not self._configured:
            logger.warning(
                "Langfuse public_key/secret_key not configured — "
                "returning empty cost analytics."
            )
            return []

        start_dt = datetime.now(UTC) - timedelta(days=days)

        # Langfuse SDK v3+: the top-level client no longer exposes `.observations()`
        # directly — observation queries go through the generated REST API client
        # at `.api.observations.get_many(...)`, which returns an
        # `ObservationsV2Response` (`.data: list[ObservationV2]`). Field names also
        # changed: `model` -> `provided_model_name`, `calculated_total_cost` ->
        # `total_cost`, and per-observation token usage -> `usage_details` (a
        # dict with an aggregate "total" key alongside per-type breakdowns).
        try:
            response = self._langfuse.api.observations.get_many(
                type="GENERATION",
                from_start_time=start_dt,
                limit=1000,
            )
        except Exception:
            logger.exception("Failed to fetch observations from Langfuse; returning empty cost analytics.")
            return []

        # Aggregate: {model_id: {date: {cost_usd, tokens}}}
        by_model: dict[str, dict[date, dict[str, float | int]]] = defaultdict(
            lambda: defaultdict(lambda: {"cost_usd": 0.0, "tokens": 0})
        )

        for obs in response.data:
            model_id = obs.provided_model_name or "unknown"
            obs_date = (obs.start_time or datetime.now(UTC)).date()
            cost_usd = obs.total_cost or 0.0
            usage_details = obs.usage_details or {}
            total_tokens = usage_details.get("total", 0) or 0

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
