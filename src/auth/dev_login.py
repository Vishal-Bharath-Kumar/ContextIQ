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
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from src.auth.keycloak_settings import KeycloakSettings
from src.auth.roles import PlatformRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class DevLoginRequest(BaseModel):
    username: str
    password: str


class DevLoginResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str = "Bearer"  # noqa: S105 — not a secret, an OAuth2 field name


class DevRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    role: PlatformRole


class DevRegisterResponse(BaseModel):
    username: str
    email: EmailStr
    assigned_role: str
    message: str


def _dev_login_enabled() -> bool:
    return os.environ.get("CONTEXTIQ_DEV_LOGIN_ENABLED", "false").lower() == "true"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _get_admin_access_token(
    client: httpx.AsyncClient,
    settings: KeycloakSettings,
) -> str:
    try:
        resp = await client.post(
            settings.admin_token_uri,
            data={
                "grant_type": "password",
                "client_id": settings.admin_client_id,
                "username": settings.admin_username,
                "password": settings.admin_password,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except httpx.HTTPError as exc:
        logger.warning("dev-register: Keycloak admin token request failed: %s", exc)
        raise HTTPException(status_code=503, detail="Auth service unavailable") from exc

    if resp.status_code >= 500:
        logger.warning(
            "dev-register: Keycloak admin token endpoint failed (status=%d, body=%s)",
            resp.status_code,
            resp.text[:500],
        )
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    if resp.status_code != 200:
        logger.warning("dev-register: Keycloak admin credentials rejected (status=%d)", resp.status_code)
        raise HTTPException(status_code=503, detail="Registration is temporarily unavailable")

    body = resp.json()
    return str(body["access_token"])


def _extract_user_id(location_header: str | None) -> str | None:
    if not location_header:
        return None
    path = urlparse(location_header).path.rstrip("/")
    user_id = path.rsplit("/", 1)[-1]
    return user_id or None


async def _lookup_user_id(
    client: httpx.AsyncClient,
    settings: KeycloakSettings,
    admin_token: str,
    username: str,
) -> str | None:
    resp = await client.get(
        settings.admin_users_uri,
        params={"username": username, "exact": "true"},
        headers=_auth_headers(admin_token),
    )
    if resp.status_code != 200:
        logger.warning(
            "dev-register: failed to lookup created user (status=%d, body=%s)",
            resp.status_code,
            resp.text[:500],
        )
        return None
    users = resp.json()
    if not isinstance(users, list) or not users:
        return None
    candidate = users[0]
    if not isinstance(candidate, dict):
        return None
    user_id = candidate.get("id")
    return str(user_id) if user_id else None


async def _assign_selected_role(
    client: httpx.AsyncClient,
    settings: KeycloakSettings,
    admin_token: str,
    user_id: str,
    role: PlatformRole,
) -> None:
    role_name = role.value
    role_resp = await client.get(
        settings.admin_realm_role_uri(role_name),
        headers=_auth_headers(admin_token),
    )
    if role_resp.status_code != 200:
        logger.warning(
            "dev-register: failed to fetch realm role %s (status=%d, body=%s)",
            role_name,
            role_resp.status_code,
            role_resp.text[:500],
        )
        raise HTTPException(status_code=503, detail="Registration is temporarily unavailable")

    mapping_resp = await client.post(
        settings.admin_user_role_mappings_uri(user_id),
        json=[role_resp.json()],
        headers=_auth_headers(admin_token),
    )
    if mapping_resp.status_code not in (200, 201, 204):
        logger.warning(
            "dev-register: failed to assign role %s to user %s (status=%d, body=%s)",
            role_name,
            user_id,
            mapping_resp.status_code,
            mapping_resp.text[:500],
        )
        raise HTTPException(status_code=503, detail="Registration is temporarily unavailable")


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

    if resp.status_code >= 500:
        logger.warning(
            "dev-login: Keycloak token endpoint failed (status=%d, body=%s)",
            resp.status_code,
            resp.text[:500],
        )
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    if resp.status_code != 200:
        logger.info("dev-login: Keycloak rejected credentials (status=%d)", resp.status_code)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    body = resp.json()
    return DevLoginResponse(access_token=body["access_token"], expires_in=body["expires_in"])


@router.post("/dev-register", response_model=DevRegisterResponse, status_code=201)
async def dev_register(payload: DevRegisterRequest) -> DevRegisterResponse:
    """Create a local-dev Keycloak user and grant the selected platform role."""
    if not _dev_login_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    allowed_roles = {
        PlatformRole.ADMIN,
        PlatformRole.DEVELOPER,
        PlatformRole.PLATFORM_ENGINEER,
    }
    if payload.role not in allowed_roles:
        raise HTTPException(status_code=400, detail="Unsupported registration role")

    settings = KeycloakSettings()

    async with httpx.AsyncClient(timeout=10.0) as client:
        admin_token = await _get_admin_access_token(client, settings)

        try:
            create_resp = await client.post(
                settings.admin_users_uri,
                json={
                    "username": payload.username,
                    "email": payload.email,
                    "firstName": payload.first_name,
                    "lastName": payload.last_name,
                    "enabled": True,
                    "emailVerified": True,
                    "credentials": [
                        {
                            "type": "password",
                            "value": payload.password,
                            "temporary": False,
                        }
                    ],
                },
                headers=_auth_headers(admin_token),
            )
        except httpx.HTTPError as exc:
            logger.warning("dev-register: Keycloak admin create-user request failed: %s", exc)
            raise HTTPException(status_code=503, detail="Registration is temporarily unavailable") from exc

        if create_resp.status_code == 409:
            raise HTTPException(status_code=409, detail="A user with this username or email already exists")
        if create_resp.status_code >= 500:
            logger.warning(
                "dev-register: Keycloak create-user failed (status=%d, body=%s)",
                create_resp.status_code,
                create_resp.text[:500],
            )
            raise HTTPException(status_code=503, detail="Registration is temporarily unavailable")
        if create_resp.status_code not in (200, 201, 204):
            logger.info(
                "dev-register: Keycloak rejected registration (status=%d, body=%s)",
                create_resp.status_code,
                create_resp.text[:500],
            )
            raise HTTPException(status_code=400, detail="Unable to register the user")

        user_id = _extract_user_id(create_resp.headers.get("Location"))
        if not user_id:
            user_id = await _lookup_user_id(client, settings, admin_token, payload.username)
        if not user_id:
            raise HTTPException(status_code=503, detail="Registration is temporarily unavailable")

        await _assign_selected_role(client, settings, admin_token, user_id, payload.role)

    return DevRegisterResponse(
        username=payload.username,
        email=payload.email,
        assigned_role=payload.role.value,
        message="Registration successful. Sign in with your new account.",
    )
