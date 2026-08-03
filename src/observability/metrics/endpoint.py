from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["Observability"])


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    include_in_schema=False,  # exclude from OpenAPI docs
    summary="Prometheus metrics scrape endpoint.",
)
async def metrics_endpoint() -> PlainTextResponse:
    """
    AC-1: Exposes all registered metrics in Prometheus text exposition format.
    Scraped by the Kubernetes ServiceMonitor on port 8080 path /metrics.
    """
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )
