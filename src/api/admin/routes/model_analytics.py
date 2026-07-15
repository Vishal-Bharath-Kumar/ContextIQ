from typing import Any

from fastapi import APIRouter, Depends

from src.auth import require_cost_analytics

# Router prefix intentionally matches the model registry prefix (/v1/models) so
# that the cost-analytics sub-route resolves to GET /v1/models/cost-analytics (AC-3).
# FastAPI dispatches each request to the router whose route handler matches —
# the MANAGE_MODELS guard on model_router.py does NOT apply to routes owned here.
router = APIRouter(
    prefix="/v1/models",
    tags=["Model Analytics"],
    dependencies=[Depends(require_cost_analytics)],
)


@router.get("/cost-analytics")
async def get_cost_analytics() -> dict[str, Any]:
    return {}
