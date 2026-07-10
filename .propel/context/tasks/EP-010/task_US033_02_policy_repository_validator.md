# TASK-US033-02 — `PolicyRepository` (PostgreSQL versioning) and `RegoValidator` (OPA syntax check)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US033-02 |
| User Story | US-033 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `PolicyRepository` — the async SQLAlchemy repository that persists every policy version in PostgreSQL while retaining all prior versions for rollback — and `RegoValidator` — which submits candidate Rego source to the OPA `/v1/compile` endpoint and returns structured parse errors. `PolicyRepository` satisfies AC-2 (version retention) and AC-5 (audit query). `RegoValidator` satisfies AC-6 (422 on invalid Rego). Both are consumed by `PolicyService` (TASK-US033-03).

## Implementation Details

**Technology:** Python 3.11+, SQLAlchemy 2.x async (`AsyncSession`), httpx `[asyncio]>=0.27`, Pydantic v2

**File locations:**
- `src/governance/policy/repository.py` — `PolicyRepository`
- `src/governance/policy/validator.py` — `RegoValidator`, `RegoValidationResult`, `RegoValidationError`
- `tests/governance/test_policy_repository.py`
- `tests/governance/test_rego_validator.py`

---

### `PolicyRepository`

```python
# src/governance/policy/repository.py
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing   import Sequence

from sqlalchemy        import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.governance.policy.models  import PolicyRecord
from src.governance.policy.schemas import PolicyStatus


class PolicyRepository:
    """
    Async repository for policy_definitions table.

    Version retention rule (AC-2):
    - Records are never deleted via this repository.
    - Status transitions: draft → active (on activate); active → superseded (when newer version activated).
    - Rollback sets the target version back to active and the current active to rolled_back.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Writes                                                               #
    # ------------------------------------------------------------------ #

    async def create(
        self,
        *,
        policy_group: str,
        version:      str,
        description:  str,
        rego_body:    str,
        author:       str,
    ) -> PolicyRecord:
        """Insert a new policy version in DRAFT status. AC-1, AC-2."""
        record = PolicyRecord(
            id           = uuid.uuid4(),
            policy_group = policy_group,
            version      = version,
            description  = description,
            rego_body    = rego_body,
            status       = PolicyStatus.DRAFT,
            author       = author,
            activated_at = None,
        )
        self._session.add(record)
        await self._session.flush()   # populate server-default created_at
        return record

    async def set_active(
        self,
        *,
        policy_id:    uuid.UUID,
        activated_at: datetime,
    ) -> PolicyRecord:
        """
        Mark `policy_id` as ACTIVE and supersede the previous active version.
        Called inside the same transaction by PolicyService (AC-3, AC-5).
        """
        # Supersede any currently active version in the same policy_group
        record = await self._get_or_raise(policy_id)
        await self._session.execute(
            update(PolicyRecord)
            .where(
                PolicyRecord.policy_group == record.policy_group,
                PolicyRecord.status       == PolicyStatus.ACTIVE,
                PolicyRecord.id           != policy_id,
            )
            .values(status=PolicyStatus.SUPERSEDED)
        )
        # Activate the target version
        record.status       = PolicyStatus.ACTIVE
        record.activated_at = activated_at
        await self._session.flush()
        return record

    async def set_rolled_back(
        self,
        *,
        current_active_id: uuid.UUID,
        target_version_id: uuid.UUID,
        activated_at:      datetime,
    ) -> PolicyRecord:
        """
        Demote `current_active_id` to ROLLED_BACK and promote `target_version_id`
        to ACTIVE. Returns the newly active record. AC-4.
        """
        current = await self._get_or_raise(current_active_id)
        current.status = PolicyStatus.ROLLED_BACK

        target             = await self._get_or_raise(target_version_id)
        target.status      = PolicyStatus.ACTIVE
        target.activated_at = activated_at
        await self._session.flush()
        return target

    # ------------------------------------------------------------------ #
    # Reads                                                                #
    # ------------------------------------------------------------------ #

    async def get_by_id(self, policy_id: uuid.UUID) -> PolicyRecord | None:
        result = await self._session.execute(
            select(PolicyRecord).where(PolicyRecord.id == policy_id)
        )
        return result.scalar_one_or_none()

    async def get_active(self, policy_group: str) -> PolicyRecord | None:
        """Return the currently active policy version for a policy group."""
        result = await self._session.execute(
            select(PolicyRecord).where(
                PolicyRecord.policy_group == policy_group,
                PolicyRecord.status       == PolicyStatus.ACTIVE,
            )
        )
        return result.scalar_one_or_none()

    async def list_versions(self, policy_group: str) -> Sequence[PolicyRecord]:
        """
        Return all versions for a policy_group in descending created_at order.
        Preserves every version — no deletions (AC-2).
        """
        result = await self._session.execute(
            select(PolicyRecord)
            .where(PolicyRecord.policy_group == policy_group)
            .order_by(PolicyRecord.created_at.desc())
        )
        return result.scalars().all()

    async def get_version(
        self, policy_group: str, version: str
    ) -> PolicyRecord | None:
        """Lookup a specific version string for rollback (AC-4)."""
        result = await self._session.execute(
            select(PolicyRecord).where(
                PolicyRecord.policy_group == policy_group,
                PolicyRecord.version      == version,
            )
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------ #
    # Private                                                              #
    # ------------------------------------------------------------------ #

    async def _get_or_raise(self, policy_id: uuid.UUID) -> PolicyRecord:
        record = await self.get_by_id(policy_id)
        if record is None:
            raise PolicyNotFoundError(str(policy_id))
        return record


class PolicyNotFoundError(Exception):
    """Raised when a policy record UUID does not exist in the database."""
```

---

### `RegoValidator`

The OPA `/v1/compile` endpoint partially evaluates a Rego query and surfaces parse/compile errors without persisting any policy. This is the lightest-weight syntax check available on the OPA HTTP API.

```python
# src/governance/policy/validator.py
from __future__ import annotations
from dataclasses import dataclass, field

import httpx


@dataclass(frozen=True)
class RegoValidationResult:
    is_valid:    bool
    errors:      list[str] = field(default_factory=list)

    @property
    def error_detail(self) -> str:
        return "; ".join(self.errors)


class RegoValidationError(Exception):
    """
    Raised when candidate Rego fails OPA syntax/compile check.
    The `errors` attribute contains the raw OPA error messages (AC-6).
    """
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class RegoValidator:
    """
    Validates Rego source by submitting it to OPA's PUT /v1/policies/{name}
    endpoint (dry-run via a transient policy name), capturing parse errors,
    then removing the transient policy with DELETE.

    OPA /v1/compile is not a full compile endpoint for arbitrary module text;
    PUT /v1/policies/{name} + DELETE is the reliable pattern for syntax checking.
    """

    _TRANSIENT_POLICY_PREFIX = "_rego_validation_"

    def __init__(
        self,
        client:   httpx.AsyncClient,
        opa_base: str = "http://localhost:8181",
    ) -> None:
        self._client   = client
        self._opa_base = opa_base.rstrip("/")

    async def validate(self, name: str, rego_body: str) -> RegoValidationResult:
        """
        Submits Rego to OPA for syntax/compile validation.
        Returns `RegoValidationResult(is_valid=True)` on success.
        Returns `RegoValidationResult(is_valid=False, errors=[...])` on failure.
        Does NOT raise — call site decides whether to raise `RegoValidationError`.
        """
        transient_name = f"{self._TRANSIENT_POLICY_PREFIX}{name}"
        url            = f"{self._opa_base}/v1/policies/{transient_name}"

        put_response = await self._client.put(
            url,
            content = rego_body.encode(),
            headers = {"Content-Type": "text/plain"},
            timeout = 5.0,
        )

        if put_response.status_code == 200:
            # Valid Rego — clean up the transient policy
            await self._client.delete(url, timeout=2.0)
            return RegoValidationResult(is_valid=True)

        # OPA returns 400 with a JSON body containing parse/compile errors
        errors = _extract_opa_errors(put_response)
        return RegoValidationResult(is_valid=False, errors=errors)


def _extract_opa_errors(response: httpx.Response) -> list[str]:
    """
    Parse the OPA error response body.
    Shape: {"code": "invalid_parameter", "message": "...", "errors": [...]}
    """
    try:
        body = response.json()
    except Exception:
        return [f"OPA returned HTTP {response.status_code}: {response.text[:256]}"]

    if "errors" in body and isinstance(body["errors"], list):
        return [
            e.get("message") or str(e)
            for e in body["errors"]
        ]
    if "message" in body:
        return [body["message"]]
    return [f"OPA returned HTTP {response.status_code}"]
```

## Acceptance Criteria

- [ ] `PolicyRepository.create()` inserts a row with `status="draft"` and does not overwrite existing versions
- [ ] `PolicyRepository.list_versions()` returns all rows for a `policy_group`, confirming no deletes (AC-2)
- [ ] `PolicyRepository.set_active()` marks the previous active row as `superseded` in the same transaction
- [ ] `PolicyRepository.set_rolled_back()` demotes the current active row and promotes the target version
- [ ] `RegoValidator.validate()` returns `is_valid=True` when OPA PUT returns 200
- [ ] `RegoValidator.validate()` returns `is_valid=False` with non-empty `errors` when OPA PUT returns 400 (AC-6)
- [ ] Transient policy is deleted from OPA after a successful validation; not left in place

## Dependencies

- TASK-US033-01 (`PolicyRecord`, `PolicyStatus`, `PolicyNotFoundError`)
- OPA sidecar reachable at `localhost:8181` (integration tests mock via `respx`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
