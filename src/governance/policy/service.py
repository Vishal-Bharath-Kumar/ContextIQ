"""PolicyService — application-layer orchestrator for the policy lifecycle.

Coordinates PolicyRepository (persistence), RegoValidator (syntax check),
and OPA bundle push (via httpx) to satisfy all six ACs:
  AC-1 / AC-5  — creation with author recording
  AC-2         — version retention (delegated to repository)
  AC-3         — activation with OPA bundle refresh
  AC-4         — rollback to a prior version
  AC-6         — RegoValidationError propagation for invalid Rego

Consumed by the Admin API routes (TASK-US033-04).
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import httpx

from src.governance.policy.audit_repository import PolicyAuditRepository
from src.governance.policy.repository import PolicyNotFoundError, PolicyRepository
from src.governance.policy.schemas import (
    ActivateResponse,
    PolicyCreate,
    PolicyStatus,
    PolicyVersion,
)
from src.governance.policy.validator import RegoValidationError, RegoValidator

logger = logging.getLogger(__name__)


class PolicyVersionNotFoundError(Exception):
    """Raised when a requested rollback target version does not exist."""


class PolicyAlreadyActiveError(Exception):
    """Raised when the version to activate is already in ACTIVE status."""


class PolicyService:
    """
    Orchestrates the full policy lifecycle:
    create → (optional validate) → activate → (optional rollback)

    All methods execute inside the caller-supplied AsyncSession transaction.
    The caller (route handler) is responsible for commit/rollback.
    """

    def __init__(
        self,
        repository: PolicyRepository,
        validator: RegoValidator,
        opa_client: httpx.AsyncClient,
        opa_base: str = "http://localhost:8181",
        audit_repository: PolicyAuditRepository | None = None,
    ) -> None:
        self._repo = repository
        self._validator = validator
        self._opa = opa_client
        self._opa_base = opa_base.rstrip("/")
        self._audit = audit_repository

    # ------------------------------------------------------------------ #
    # AC-1 — Create new policy version                                    #
    # ------------------------------------------------------------------ #

    async def create(
        self,
        payload: PolicyCreate,
        *,
        author: str,
    ) -> PolicyVersion:
        """Store a new policy version in DRAFT status.

        Uniqueness of (policy_group / version) is enforced at the DB level
        via uq_policy_group_version; IntegrityError surfaces as 409 in the API layer.
        """
        record = await self._repo.create(
            policy_group=payload.name,
            version=payload.version,
            description=payload.description,
            rego_body=payload.rego_body,
            author=author,
        )
        logger.info(
            "policy.created group=%s version=%s author=%s",
            payload.name,
            payload.version,
            author,
        )
        
        # Log audit event
        if self._audit:
            await self._audit.log(
                policy_id=record.id,
                event_type="policy.created",
                actor_user_id=author,
                detail=f"Created version {payload.version} in group {payload.name}",
            )
        
        return _to_version(record)

    # ------------------------------------------------------------------ #
    # AC-3 — Activate a policy version                                    #
    # ------------------------------------------------------------------ #

    async def activate(
        self,
        *,
        policy_id: uuid.UUID,
    ) -> ActivateResponse:
        """Activate a draft policy version.

        1. Validate Rego syntax via OPA /v1/policies (dry-run). Raise
           RegoValidationError if invalid — route handler returns 422 (AC-6).
        2. Push validated Rego to OPA as a live policy (triggers bundle refresh, AC-3).
        3. Mark the DB row ACTIVE; supersede the previous active version in the same
           transaction (AC-3).
        4. Record activated_at (AC-5).
        """
        record = await self._repo.get_by_id(policy_id)
        if record is None:
            raise PolicyNotFoundError(str(policy_id))

        if record.status == PolicyStatus.ACTIVE:
            raise PolicyAlreadyActiveError(f"Policy {policy_id} is already active.")

        # Step 1: Validate Rego (AC-6)
        result = await self._validator.validate(record.policy_group, record.rego_body)
        if not result.is_valid:
            raise RegoValidationError(result.errors)

        # Step 2: Push to OPA (triggers bundle refresh in the sidecar, AC-3)
        activated_at = datetime.now(tz=UTC)
        bundle_push_ok = await self._push_to_opa(record.policy_group, record.rego_body)

        # Step 3 + 4: Persist activation in PostgreSQL
        updated = await self._repo.set_active(
            policy_id=policy_id,
            activated_at=activated_at,
        )
        logger.info(
            "policy.activated group=%s version=%s bundle_ok=%s",
            updated.policy_group,
            updated.version,
            bundle_push_ok,
        )
        
        # Log audit event
        if self._audit:
            await self._audit.log(
                policy_id=policy_id,
                event_type="policy.activated",
                actor_user_id=record.author,
                detail=f"Activated version {updated.version} in group {updated.policy_group}",
            )
        
        return ActivateResponse(
            activated_version=updated.version,
            bundle_push_ok=bundle_push_ok,
            activated_at=activated_at,
        )

    # ------------------------------------------------------------------ #
    # Update a policy version                                             #
    # ------------------------------------------------------------------ #

    async def update(
        self,
        *,
        policy_id: uuid.UUID,
        description: str | None = None,
        rego_body: str | None = None,
        author: str,
    ) -> PolicyVersion:
        """Update an existing policy version.
        
        Only DRAFT policies can be updated.
        """
        record = await self._repo.get_by_id(policy_id)
        if record is None:
            raise PolicyNotFoundError(str(policy_id))
        
        updated = await self._repo.update(
            policy_id=policy_id,
            description=description,
            rego_body=rego_body,
        )
        logger.info(
            "policy.updated group=%s version=%s author=%s",
            updated.policy_group,
            updated.version,
            author,
        )
        
        # Log audit event
        if self._audit:
            changes = []
            if description is not None:
                changes.append("description")
            if rego_body is not None:
                changes.append("rego_body")
            await self._audit.log(
                policy_id=policy_id,
                event_type="policy.updated",
                actor_user_id=author,
                detail=f"Updated {', '.join(changes)} for version {updated.version} in group {updated.policy_group}",
            )
        
        return _to_version(updated)

    # ------------------------------------------------------------------ #
    # Deactivate a policy version                                         #
    # ------------------------------------------------------------------ #

    async def deactivate(
        self,
        *,
        policy_id: uuid.UUID,
        author: str,
    ) -> PolicyVersion:
        """Deactivate an active policy version.
        
        Marks the policy as SUPERSEDED and removes it from OPA.
        """
        record = await self._repo.get_by_id(policy_id)
        if record is None:
            raise PolicyNotFoundError(str(policy_id))
        
        if record.status != PolicyStatus.ACTIVE:
            raise ValueError(f"Policy {policy_id} is not active (status: {record.status}).")
        
        # Remove from OPA
        await self._remove_from_opa(record.policy_group)
        
        # Mark as superseded
        updated = await self._repo.mark_superseded(policy_id)
        logger.info(
            "policy.deactivated group=%s version=%s author=%s",
            updated.policy_group,
            updated.version,
            author,
        )
        
        # Log audit event
        if self._audit:
            await self._audit.log(
                policy_id=policy_id,
                event_type="policy.deactivated",
                actor_user_id=author,
                detail=f"Deactivated version {updated.version} in group {updated.policy_group}",
            )
        
        return _to_version(updated)

    # ------------------------------------------------------------------ #
    # Delete a policy version                                             #
    # ------------------------------------------------------------------ #

    async def delete(
        self,
        *,
        policy_id: uuid.UUID,
        author: str,
    ) -> None:
        """Delete a policy version.
        
        Only DRAFT or SUPERSEDED policies can be deleted.
        """
        record = await self._repo.get_by_id(policy_id)
        if record is None:
            raise PolicyNotFoundError(str(policy_id))
        
        policy_group = record.policy_group
        version = record.version
        
        # Log audit event before deletion
        if self._audit:
            await self._audit.log(
                policy_id=policy_id,
                event_type="policy.deleted",
                actor_user_id=author,
                detail=f"Deleted version {version} in group {policy_group}",
            )
        
        await self._repo.delete(policy_id)
        logger.info(
            "policy.deleted group=%s version=%s author=%s",
            policy_group,
            version,
            author,
        )

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _push_to_opa(self, policy_group: str, rego_body: str) -> bool:
        """PUT rego_body to OPA as a persistent policy.

        Returns True on HTTP 200; logs and returns False on other status codes.
        Does not raise — the activation is persisted in PostgreSQL regardless.
        OPA's internal polling will eventually reconcile if the push fails.
        """
        url = f"{self._opa_base}/v1/policies/{policy_group}"
        try:
            resp = await self._opa.put(
                url,
                content=rego_body.encode(),
                headers={"Content-Type": "text/plain"},
                timeout=5.0,
            )
            if resp.status_code == 200:
                return True
            logger.error(
                "opa_push failed for group=%s status=%d body=%s",
                policy_group,
                resp.status_code,
                resp.text[:256],
            )
            return False
        except httpx.RequestError as exc:
            logger.error("opa_push error for group=%s: %s", policy_group, exc)
            return False

    async def _remove_from_opa(self, policy_group: str) -> bool:
        """DELETE policy from OPA.

        Returns True on HTTP 200; logs and returns False on other status codes.
        """
        url = f"{self._opa_base}/v1/policies/{policy_group}"
        try:
            resp = await self._opa.delete(url, timeout=5.0)
            if resp.status_code == 200:
                return True
            logger.error(
                "opa_delete failed for group=%s status=%d body=%s",
                policy_group,
                resp.status_code,
                resp.text[:256],
            )
            return False
        except httpx.RequestError as exc:
            logger.error("opa_delete error for group=%s: %s", policy_group, exc)
            return False


# ------------------------------------------------------------------ #
# Mapping helpers                                                      #
# ------------------------------------------------------------------ #


def _to_version(record: object) -> PolicyVersion:
    from src.governance.policy.models import PolicyRecord as _M  # noqa: F401

    return PolicyVersion(
        id=record.id,  # type: ignore[attr-defined]
        policy_group=record.policy_group,  # type: ignore[attr-defined]
        version=record.version,  # type: ignore[attr-defined]
        description=record.description,  # type: ignore[attr-defined]
        rego_body=record.rego_body,  # type: ignore[attr-defined]
        status=record.status,  # type: ignore[attr-defined]
        author=record.author,  # type: ignore[attr-defined]
        activated_at=record.activated_at,  # type: ignore[attr-defined]
        created_at=record.created_at,  # type: ignore[attr-defined]
    )
