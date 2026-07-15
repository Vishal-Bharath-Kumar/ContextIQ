from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.dependencies import get_read_db    # AC-6: read replica
from src.analytics.cost.query_repository import CostAnalyticsQueryRepository

router = APIRouter(prefix="/v1/cost-analytics", tags=["cost-analytics"])


@router.get("")
async def list_cost_analytics(
    limit:  int = Query(default=50, le=200),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_read_db),    # AC-6: reporting reads → replica
) -> dict:
    repo = CostAnalyticsQueryRepository(db)
    return await repo.list(limit=limit, cursor=cursor)
