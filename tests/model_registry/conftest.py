"""Shared fixtures for tests/model_registry/.

Provides:
  - ``bypass_jwt_middleware`` — autouse, patches JWTAuthMiddleware.dispatch so
    requests reach routes without a real Bearer token.  RBAC enforcement via
    FastAPI dependency overrides is still exercised.
"""
from __future__ import annotations

import pytest

from src.auth.middleware import JWTAuthMiddleware


@pytest.fixture(autouse=True)
def bypass_jwt_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace JWTAuthMiddleware.dispatch with a pass-through for all model_registry tests."""
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    async def _passthrough(  # type: ignore[misc]
        self: JWTAuthMiddleware,
        request: Request,
        call_next: ASGIApp,
    ) -> Response:
        return await call_next(request)

    monkeypatch.setattr(JWTAuthMiddleware, "dispatch", _passthrough)
