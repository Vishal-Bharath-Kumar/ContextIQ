# TASK-US033-03 — `PolicyService` (Create, Activate, Rollback, Audit)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US033-03 |
| User Story | US-033 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `PolicyService` — the application-layer orchestrator for the policy lifecycle. It coordinates `PolicyRepository` (persistence), `RegoValidator` (syntax check), and an OPA bundle push (via `httpx`) to satisfy all six ACs: creation with author recording (AC-1, AC-5), version retention (AC-2), activation with OPA bundle refresh (AC-3), rollback (AC-4), and `RegoValidationError` propagation for invalid Rego (AC-6). `PolicyService` is consumed by the Admin API routes (TASK-US033-04).

## Implementation Details

**Technology:** Python 3.11+, SQLAlchemy 2.x async, httpx `[asyncio]>=0.27`, Pydantic v2

**File locations:**
- `src/governance/policy/service.py` — `PolicyService`
- `tests/governance/test_policy_service.py`

---

### `PolicyService`

```python
# src/governance/policy/service.py
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone

import httpx

from src.governance.policy.repository import PolicyRepository, PolicyNotFoundError
from src.governance.policy.schemas    import (
    PolicyCreate,
    PolicyVersion,
    PolicySummary,
    ActivateResponse,
    RollbackResponse,
    PolicyStatus,
)
from src.governance.policy.validator  import RegoValidator, RegoValidationError

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
        validator:  RegoValidator,
        opa_client: httpx.AsyncClient,
        opa_base:   str = "http://localhost:8181",
    ) -> None:
        self._repo      = repository
        self._validator = validator
        self._opa       = opa_client
        self._opa_base  = opa_base.rstrip("/")

    # ------------------------------------------------------------------ #
    # AC-1 — Create new policy version                                    #
    # ------------------------------------------------------------------ #

    async def create(
        self,
        payload: PolicyCreate,
        *,
        author: str,    # sub claim from the decoded admin JWT (AC-5)
    ) -> PolicyVersion:
        """
        Store a new policy version in DRAFT status.
        Uniqueness of (policy_group / version) is enforced at the DB level
        via uq_policy_group_version; IntegrityError surfaces as 409 in the API layer.
        """
        record = await self._repo.create(
            policy_group = payload.name,
            version      = payload.version,
            description  = payload.description,
            rego_body    = payload.rego_body,
            author       = author,
        )
        logger.info(
            "policy.created group=%s version=%s author=%s",
            payload.name, payload.version, author,
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
        """
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
            raise PolicyAlreadyActiveError(
                f"Policy {policy_id} is already active."
            )

        # Step 1: Validate Rego (AC-6)
        result = await self._validator.validate(record.policy_group, record.rego_body)
        if not result.is_valid:
            raise RegoValidationError(result.errors)

        # Step 2: Push to OPA (triggers bundle refresh in the sidecar, AC-3)
        activated_at  = datetime.now(tz=timezone.utc)
        bundle_push_ok = await self._push_to_opa(record.policy_group, record.rego_body)

        # Step 3 + 4: Persist activation in PostgreSQL
        updated = await self._repo.set_active(
            policy_id    = policy_id,
            activated_at = activated_at,
        )
        logger.info(
            "policy.activated group=%s version=%s bundle_ok=%s",
            updated.policy_group, updated.version, bundle_push_ok,
        )
        return ActivateResponse(
            activated_version = updated.version,
            bundle_push_ok    = bundle_push_ok,
            activated_at      = activated_at,
        )

    # ------------------------------------------------------------------ #
    # AC-4 — Roll back to a prior version                                 #
    # ------------------------------------------------------------------ #

    async def rollback(
        self,
        *,
        policy_group: str,
        target_version: str,    # from ?version=N query param (AC-4)
    ) -> RollbackResponse:
        """
        1. Locate the currently active version and the target version.
        2. Push the target Rego to OPA.
        3. Demote the current active to ROLLED_BACK; promote the target to ACTIVE.
        4. Record activated_at on the restored version (AC-5).
        """
        current_active = await self._repo.get_active(policy_group)
        if current_active is None:
            raise PolicyVersionNotFoundError(
                f"No active policy found for group '{policy_group}'."
            )

        target = await self._repo.get_version(policy_group, target_version)
        if target is None:
            raise PolicyVersionNotFoundError(
                f"Version '{target_version}' not found in group '{policy_group}'."
            )

        # Re-validate the target Rego before reinstating it (safety net)
        result = await self._validator.validate(policy_group, target.rego_body)
        if not result.is_valid:
            raise RegoValidationError(result.errors)

        activated_at   = datetime.now(tz=timezone.utc)
        previous_label = current_active.version

        await self._push_to_opa(policy_group, target.rego_body)

        await self._repo.set_rolled_back(
            current_active_id = current_active.id,
            target_version_id = target.id,
            activated_at      = activated_at,
        )
        logger.info(
            "policy.rolled_back group=%s from=%s to=%s",
            policy_group, previous_label, target_version,
        )
        return RollbackResponse(
            restored_version = target_version,
            previous_active  = previous_label,
            activated_at     = activated_at,
        )

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _push_to_opa(self, policy_group: str, rego_body: str) -> bool:
        """
        PUT rego_body to OPA as a persistent policy.
        Returns True on HTTP 200; logs and returns False on other status codes.
        Does not raise — the activation is persisted in PostgreSQL regardless.
        OPA's internal polling will eventually reconcile if the push fails.
        """
        url = f"{self._opa_base}/v1/policies/{policy_group}"
        try:
            resp = await self._opa.put(
                url,
                content = rego_body.encode(),
                headers = {"Content-Type": "text/plain"},
                timeout = 5.0,
            )
            if resp.status_code == 200:
                return True
            logger.error(
                "opa_push failed for group=%s status=%d body=%s",
                policy_group, resp.status_code, resp.text[:256],
            )
            return False
        except httpx.RequestError as exc:
            logger.error("opa_push error for group=%s: %s", policy_group, exc)
            return False


# ------------------------------------------------------------------ #
# Mapping helpers                                                      #
# ------------------------------------------------------------------ #

def _to_version(record) -> PolicyVersion:
    from src.governance.policy.models import PolicyRecord as M
    return PolicyVersion(
        id           = record.id,
        policy_group = record.policy_group,
        version      = record.version,
        description  = record.description,
        rego_body    = record.rego_body,
        status       = record.status,
        author       = record.author,
        activated_at = record.activated_at,
        created_at   = record.created_at,
    )
```

## Acceptance Criteria

- [ ] `PolicyService.create()` stores `author` from the caller and returns a `PolicyVersion` with `status="draft"`
- [ ] `PolicyService.activate()` calls `RegoValidator.validate()` before pushing to OPA; raises `RegoValidationError` on failure (AC-6)
- [ ] `PolicyService.activate()` calls `_push_to_opa()` with the Rego body (AC-3)
- [ ] After `activate()`, the DB row has `status="active"` and a non-null `activated_at` (AC-5)
- [ ] After `activate()`, the previously active row has `status="superseded"` (verified via `list_versions()`)
- [ ] `PolicyService.rollback()` raises `PolicyVersionNotFoundError` when the target version does not exist
- [ ] After `rollback()`, the target version has `status="active"` and the prior active has `status="rolled_back"` (AC-4)

## Dependencies

- TASK-US033-01 (`PolicyRecord`, `PolicyCreate`, `PolicyVersion`, `PolicyStatus`)
- TASK-US033-02 (`PolicyRepository`, `RegoValidator`, `RegoValidationError`, `PolicyNotFoundError`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
