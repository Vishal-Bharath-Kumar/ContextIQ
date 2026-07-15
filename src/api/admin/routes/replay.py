from typing import Any

from fastapi import APIRouter, Depends

from src.auth import require_read_traces

router = APIRouter(
    prefix="/v1/traces",
    tags=["Replay Explorer"],
    dependencies=[Depends(require_read_traces)],
)


@router.get("")
async def list_traces() -> list[dict[str, Any]]:
    return []
