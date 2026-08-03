"""
AuditContext — request-scoped FastAPI dependency for audit logging.

Captures the caller's IP address and JWT `sub` claim from the incoming
request and wraps `AdminAuditRepository` behind a convenience `log()` method.

Inject into mutating route handlers via::

    audit: Annotated[AuditContext, Depends(get_audit_context)]

The shared `AsyncSession` injected here is the SAME session instance used by
the route handler (FastAPI's `Depends` caches within the request scope), so
the audit write and the business-logic write commit atomically.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.admin_audit_log.repository import AdminAuditRepository
from src.audit.admin_audit_log.schemas import AdminActionType, AuditLogCreateRequest
from src.auth.dependencies import decode_jwt_claims
from src.gateway.schemas.auth_types import JWTClaims

# BUG FIX (spec): `from src.db.session import get_session` does not exist.
# The writable session dependency is `get_db` in `src.data.dependencies`.
from src.data.dependencies import get_db


def _extract_ip(request: Request) -> str:
    """
    Return the caller's IP address.

    Prefers the first value of ``X-Forwarded-For`` (set by the nginx Ingress
    controller) over the direct socket peer address.  Falls back to
    ``"unknown"`` when neither is available.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class AuditContext:
    """
    Request-scoped audit helper.

    Captures ``actor_user_id`` (from JWT ``sub``) and ``ip_address`` once per
    request; all subsequent ``log()`` calls reuse those values.

    Example usage in a route handler::

        @router.post("/v1/policies", status_code=201)
        async def create_policy(
            body:    PolicyCreateRequest,
            audit:   Annotated[AuditContext, Depends(get_audit_context)],
            session: Annotated[AsyncSession, Depends(get_db)],
        ) -> PolicyResponse:
            created = await policy_service.create(body, session)
            await audit.log(
                action        = AdminActionType.POLICY_CREATED,
                resource_type = "policy",
                resource_id   = str(created.id),
                before_state  = None,
                after_state   = created.model_dump(mode="json"),
            )
            await session.commit()
            return created
    """

    def __init__(
        self,
        request: Request,
        claims: JWTClaims,
        session: AsyncSession,
    ) -> None:
        self._ip = _extract_ip(request)
        self._actor = claims.sub
        self._repo = AdminAuditRepository(session)

    async def log(
        self,
        *,
        action: AdminActionType,
        resource_type: str,
        resource_id: str,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
    ) -> None:
        """Append one audit row.  Does not commit — the caller owns the transaction."""
        await self._repo.log(
            AuditLogCreateRequest(
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                actor_user_id=self._actor,
                ip_address=self._ip,
                before_state=before_state,
                after_state=after_state,
            )
        )


async def get_audit_context(
    request: Request,
    claims: Annotated[JWTClaims, Depends(decode_jwt_claims)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuditContext:
    """FastAPI dependency factory — returns a per-request `AuditContext`."""
    return AuditContext(request=request, claims=claims, session=session)
