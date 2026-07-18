from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.auth import require_cost_analytics
from src.observability.cost.analytics_service import ModelCostAnalyticsService, ModelCostSummary

# Router prefix intentionally matches the model registry prefix (/v1/models) so
# that the cost-analytics sub-route resolves to GET /v1/models/cost-analytics (AC-4).
# FastAPI dispatches each request to the router whose route handler matches —
# the MANAGE_MODELS guard on model_router.py does NOT apply to routes owned here.
router = APIRouter(
    prefix="/v1/models",
    tags=["Model Analytics"],
    dependencies=[Depends(require_cost_analytics)],
)

_Claims = Annotated[dict, Depends(require_cost_analytics)]


@router.get(
    "/cost-analytics",
    response_model=list[ModelCostSummary],
    summary="Per-model LLM cost totals and daily sparkline series (AC-4).",
)
async def get_model_cost_analytics(
    days: int = Query(default=30, ge=1, le=90, description="Lookback window in days"),
) -> list[ModelCostSummary]:
    svc = ModelCostAnalyticsService()
    return await svc.get_model_cost_summary(days=days)
