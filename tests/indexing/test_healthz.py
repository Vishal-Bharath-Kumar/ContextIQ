from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from src.indexing.main import create_app


def test_healthz_reports_opa_disabled() -> None:
    app = create_app()

    @asynccontextmanager
    async def _noop_lifespan(_: object) -> AsyncGenerator[None, None]:
        yield

    app.router.lifespan_context = _noop_lifespan

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["opa"] == {
        "status": "disabled",
        "configured": False,
        "bundle_ready": False,
        "degraded": False,
        "bundle_version": None,
        "error": None,
    }