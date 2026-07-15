from typing import Any

from fastapi import APIRouter, Body, Depends

from src.auth import require_context_tools

mcp_router = APIRouter(
    prefix="/tools",
    tags=["MCP Tools"],
    dependencies=[Depends(require_context_tools)],
)


@mcp_router.post("/context_query")
async def context_query(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return {"result": "stub"}
