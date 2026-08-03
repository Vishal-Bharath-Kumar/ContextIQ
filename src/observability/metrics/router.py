from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from src.auth import require_read_metrics

try:
    from prometheus_client import CONTENT_TYPE_LATEST as _CONTENT_TYPE
    from prometheus_client import generate_latest as _generate_latest

    def _metrics_body() -> bytes:
        return _generate_latest()  # type: ignore[no-any-return]

    _MEDIA_TYPE: str = _CONTENT_TYPE
except ImportError:  # pragma: no cover
    def _metrics_body() -> bytes:
        return b"# prometheus_client not installed\n"

    _MEDIA_TYPE = "text/plain; version=0.0.4; charset=utf-8"

metrics_router = APIRouter(dependencies=[Depends(require_read_metrics)])


@metrics_router.get("/metrics")
async def prometheus_metrics() -> Response:
    return Response(_metrics_body(), media_type=_MEDIA_TYPE)
