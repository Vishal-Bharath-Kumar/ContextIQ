"""
Local-development login route — exchanges a username/password for a real
Keycloak-issued JWT via the OAuth2 Resource Owner Password Credentials grant.

This is NOT the production auth flow (that's the full browser-redirect OIDC
authorization-code flow, not yet implemented — see TASK-US004-01). It exists
solely so the Admin Portal can be exercised locally without standing up the
full redirect/callback flow: the returned token is a genuine Keycloak JWT and
is validated normally by ``JWTAuthMiddleware`` / ``JWKSClient`` on every
subsequent request — no auth bypass is introduced.

Disabled by default. Enable only in local/dev environments via
``CONTEXTIQ_DEV_LOGIN_ENABLED=true``. Must never be enabled in production
(the client_secret and password grant are inherently dev/test-user only —
Keycloak's ``directAccessGrantsEnabled`` is on for this client for that
reason and no confidential secret is exposed to the browser; the exchange
happens server-side).
"""
from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.auth.keycloak_settings import KeycloakSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class DevLoginRequest(BaseModel):
    username: str
    password: str


class DevLoginResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str = "Bearer"  # noqa: S105 — not a secret, an OAuth2 field name


def _dev_login_enabled() -> bool:
    return os.environ.get("CONTEXTIQ_DEV_LOGIN_ENABLED", "false").lower() == "true"


@router.post("/dev-login", response_model=DevLoginResponse)
async def dev_login(payload: DevLoginRequest) -> DevLoginResponse:
    """Exchange local-dev test-user credentials for a real Keycloak JWT.

    Returns 404 when disabled so the route's existence isn't leaked in
    environments where it's off (matches default-deny posture).
    """
    if not _dev_login_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    settings = KeycloakSettings()

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                settings.token_uri,
                data={
                    "grant_type": "password",
                    "client_id": settings.client_id,
                    "client_secret": settings.client_secret,
                    "username": payload.username,
                    "password": payload.password,
                    "scope": "openid profile email roles",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            logger.warning("dev-login: Keycloak token endpoint unreachable: %s", exc)
            raise HTTPException(status_code=503, detail="Auth service unavailable") from exc

    if resp.status_code != 200:
        logger.info("dev-login: Keycloak rejected credentials (status=%d)", resp.status_code)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    body = resp.json()
    return DevLoginResponse(access_token=body["access_token"], expires_in=body["expires_in"])
