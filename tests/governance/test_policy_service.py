"""Unit tests for PolicyService — TASK-US033-03.

Uses AsyncMock for PolicyRepository and RegoValidator, respx for httpx OPA calls.
All seven ACs are covered.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from src.governance.policy.repository import PolicyNotFoundError, PolicyRepository
from src.governance.policy.schemas import (
    ActivateResponse,
    PolicyCreate,
    PolicyStatus,
    PolicyVersion,
    RollbackResponse,
)
from src.governance.policy.service import (
    PolicyAlreadyActiveError,
    PolicyService,
    PolicyVersionNotFoundError,
)
from src.governance.policy.validator import (
    RegoValidationError,
    RegoValidationResult,
    RegoValidator,
)

_OPA_BASE = "http://localhost:8181"
_VALID_REGO = "package acl\n\nallow = true\n"
_INVALID_REGO = "package acl\n\nallow =\n"


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #


def _make_policy_record(
    *,
    policy_id: uuid.UUID | None = None,
    policy_group: str = "acl",
    version: str = "1.0.0",
    rego_body: str = _VALID_REGO,
    status: PolicyStatus = PolicyStatus.DRAFT,
    author: str = "alice",
) -> MagicMock:
    record = MagicMock()
    record.id = policy_id or uuid.uuid4()
    record.policy_group = policy_group
    record.version = version
    record.rego_body = rego_body
    record.status = status
    record.description = "Test policy"
    record.author = author
    record.activated_at = None
    record.created_at = datetime.now(tz=UTC)
    return record


def _make_service(
    *,
    repo: PolicyRepository | None = None,
    validator: RegoValidator | None = None,
    opa_client: httpx.AsyncClient | None = None,
) -> tuple[PolicyService, PolicyRepository, RegoValidator]:
    repo = repo or AsyncMock(spec=PolicyRepository)
    validator = validator or AsyncMock(spec=RegoValidator)
    opa_client = opa_client or AsyncMock(spec=httpx.AsyncClient)
    svc = PolicyService(
        repository=repo,
        validator=validator,
        opa_client=opa_client,
        opa_base=_OPA_BASE,
    )
    return svc, repo, validator


# ------------------------------------------------------------------ #
# create() — AC-1, AC-5                                               #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_create_stores_author_and_returns_draft() -> None:
    """AC-1 / AC-5 — create() records author; returned status is DRAFT."""
    record = _make_policy_record(status=PolicyStatus.DRAFT, author="bob")
    svc, repo, _ = _make_service()
    repo.create = AsyncMock(return_value=record)

    payload = PolicyCreate(
        name="acl",
        version="1.0.0",
        description="Test",
        rego_body=_VALID_REGO,
    )
    result = await svc.create(payload, author="bob")

    repo.create.assert_awaited_once_with(
        policy_group="acl",
        version="1.0.0",
        description="Test",
        rego_body=_VALID_REGO,
        author="bob",
    )
    assert isinstance(result, PolicyVersion)
    assert result.status == PolicyStatus.DRAFT
    assert result.author == "bob"


# ------------------------------------------------------------------ #
# activate() — AC-3, AC-5, AC-6                                       #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_activate_calls_validator_before_opa_push() -> None:
    """AC-6 — RegoValidator.validate() is called before OPA push."""
    record = _make_policy_record(status=PolicyStatus.DRAFT)
    updated = _make_policy_record(status=PolicyStatus.ACTIVE)

    svc, repo, validator = _make_service()
    repo.get_by_id = AsyncMock(return_value=record)
    repo.set_active = AsyncMock(return_value=updated)
    validator.validate = AsyncMock(return_value=RegoValidationResult(is_valid=True))

    with respx.mock:
        respx.put(f"{_OPA_BASE}/v1/policies/{record.policy_group}").mock(
            return_value=httpx.Response(200)
        )
        # Use a real httpx client so respx can intercept
        async with httpx.AsyncClient() as client:
            svc._opa = client
            await svc.activate(policy_id=record.id)

    validator.validate.assert_awaited_once_with(
        record.policy_group, record.rego_body
    )


@pytest.mark.asyncio
async def test_activate_raises_rego_validation_error_on_invalid_rego() -> None:
    """AC-6 — activate() raises RegoValidationError when Rego is invalid."""
    record = _make_policy_record(status=PolicyStatus.DRAFT, rego_body=_INVALID_REGO)

    svc, repo, validator = _make_service()
    repo.get_by_id = AsyncMock(return_value=record)
    validator.validate = AsyncMock(
        return_value=RegoValidationResult(is_valid=False, errors=["syntax error"])
    )

    with pytest.raises(RegoValidationError):
        await svc.activate(policy_id=record.id)

    # OPA push must NOT happen
    repo.set_active.assert_not_called()


@pytest.mark.asyncio
async def test_activate_raises_when_policy_not_found() -> None:
    """PolicyNotFoundError raised when policy_id does not exist."""
    svc, repo, _ = _make_service()
    repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(PolicyNotFoundError):
        await svc.activate(policy_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_activate_raises_already_active() -> None:
    """PolicyAlreadyActiveError raised when policy is already ACTIVE."""
    record = _make_policy_record(status=PolicyStatus.ACTIVE)
    svc, repo, _ = _make_service()
    repo.get_by_id = AsyncMock(return_value=record)

    with pytest.raises(PolicyAlreadyActiveError):
        await svc.activate(policy_id=record.id)


@pytest.mark.asyncio
async def test_activate_returns_activate_response_with_bundle_push_ok() -> None:
    """AC-3 / AC-5 — activate() pushes to OPA and returns ActivateResponse."""
    record = _make_policy_record(status=PolicyStatus.DRAFT)
    updated = _make_policy_record(status=PolicyStatus.ACTIVE)

    svc, repo, validator = _make_service()
    repo.get_by_id = AsyncMock(return_value=record)
    repo.set_active = AsyncMock(return_value=updated)
    validator.validate = AsyncMock(return_value=RegoValidationResult(is_valid=True))

    with respx.mock:
        respx.put(f"{_OPA_BASE}/v1/policies/{record.policy_group}").mock(
            return_value=httpx.Response(200)
        )
        async with httpx.AsyncClient() as client:
            svc._opa = client
            response = await svc.activate(policy_id=record.id)

    assert isinstance(response, ActivateResponse)
    assert response.bundle_push_ok is True
    assert response.activated_version == updated.version
    assert response.activated_at is not None

    repo.set_active.assert_awaited_once()


@pytest.mark.asyncio
async def test_activate_bundle_push_returns_false_on_non_200() -> None:
    """_push_to_opa() returns False (does not raise) when OPA returns non-200."""
    record = _make_policy_record(status=PolicyStatus.DRAFT)
    updated = _make_policy_record(status=PolicyStatus.ACTIVE)

    svc, repo, validator = _make_service()
    repo.get_by_id = AsyncMock(return_value=record)
    repo.set_active = AsyncMock(return_value=updated)
    validator.validate = AsyncMock(return_value=RegoValidationResult(is_valid=True))

    with respx.mock:
        respx.put(f"{_OPA_BASE}/v1/policies/{record.policy_group}").mock(
            return_value=httpx.Response(500, text="internal error")
        )
        async with httpx.AsyncClient() as client:
            svc._opa = client
            response = await svc.activate(policy_id=record.id)

    assert response.bundle_push_ok is False
    # DB activation still happened
    repo.set_active.assert_awaited_once()


# ------------------------------------------------------------------ #
# rollback() — AC-4, AC-5                                             #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_rollback_raises_when_no_active_version() -> None:
    """PolicyVersionNotFoundError raised when no active version exists."""
    svc, repo, _ = _make_service()
    repo.get_active = AsyncMock(return_value=None)

    with pytest.raises(PolicyVersionNotFoundError, match="No active policy"):
        await svc.rollback(policy_group="acl", target_version="0.9.0")


@pytest.mark.asyncio
async def test_rollback_raises_when_target_version_not_found() -> None:
    """AC-4 — PolicyVersionNotFoundError raised when target version is missing."""
    current = _make_policy_record(status=PolicyStatus.ACTIVE, version="1.0.0")
    svc, repo, _ = _make_service()
    repo.get_active = AsyncMock(return_value=current)
    repo.get_version = AsyncMock(return_value=None)

    with pytest.raises(PolicyVersionNotFoundError, match="not found in group"):
        await svc.rollback(policy_group="acl", target_version="0.9.0")


@pytest.mark.asyncio
async def test_rollback_raises_rego_validation_error_for_invalid_target() -> None:
    """rollback() re-validates target Rego; raises RegoValidationError if invalid."""
    current = _make_policy_record(status=PolicyStatus.ACTIVE, version="1.0.0")
    target = _make_policy_record(
        status=PolicyStatus.DRAFT, version="0.9.0", rego_body=_INVALID_REGO
    )

    svc, repo, validator = _make_service()
    repo.get_active = AsyncMock(return_value=current)
    repo.get_version = AsyncMock(return_value=target)
    validator.validate = AsyncMock(
        return_value=RegoValidationResult(is_valid=False, errors=["parse error"])
    )

    with pytest.raises(RegoValidationError):
        await svc.rollback(policy_group="acl", target_version="0.9.0")


@pytest.mark.asyncio
async def test_rollback_demotes_current_and_promotes_target() -> None:
    """AC-4 / AC-5 — rollback() returns RollbackResponse with correct versions."""
    current = _make_policy_record(
        status=PolicyStatus.ACTIVE, version="1.0.0", policy_group="acl"
    )
    target = _make_policy_record(
        status=PolicyStatus.DRAFT, version="0.9.0", policy_group="acl"
    )

    svc, repo, validator = _make_service()
    repo.get_active = AsyncMock(return_value=current)
    repo.get_version = AsyncMock(return_value=target)
    validator.validate = AsyncMock(return_value=RegoValidationResult(is_valid=True))
    repo.set_rolled_back = AsyncMock(return_value=target)

    with respx.mock:
        respx.put(f"{_OPA_BASE}/v1/policies/acl").mock(
            return_value=httpx.Response(200)
        )
        async with httpx.AsyncClient() as client:
            svc._opa = client
            response = await svc.rollback(
                policy_group="acl", target_version="0.9.0"
            )

    assert isinstance(response, RollbackResponse)
    assert response.restored_version == "0.9.0"
    assert response.previous_active == "1.0.0"
    assert response.activated_at is not None

    repo.set_rolled_back.assert_awaited_once_with(
        current_active_id=current.id,
        target_version_id=target.id,
        activated_at=response.activated_at,
    )


# ------------------------------------------------------------------ #
# _push_to_opa() edge cases                                           #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_push_to_opa_returns_false_on_request_error() -> None:
    """_push_to_opa() catches httpx.RequestError and returns False without raising."""
    svc, _, _ = _make_service()

    with respx.mock:
        respx.put(f"{_OPA_BASE}/v1/policies/acl").mock(
            side_effect=httpx.ConnectError("refused")
        )
        async with httpx.AsyncClient() as client:
            svc._opa = client
            ok = await svc._push_to_opa("acl", _VALID_REGO)

    assert ok is False


# ------------------------------------------------------------------ #
# TASK-US033-05 — AC-3/4/5 service integration tests                 #
# (backed by in-memory SQLite via async_session from conftest.py)    #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_activate_pushes_rego_to_opa(async_session) -> None:
    """AC-3: activate() calls OPA PUT /v1/policies/{name} with the Rego body."""
    from tests.governance.conftest import VALID_REGO, POLICY_NAME, ADMIN_AUTHOR

    repo = PolicyRepository(async_session)
    record = await repo.create(
        policy_group=POLICY_NAME,
        version="1.0.0",
        description="",
        rego_body=VALID_REGO,
        author=ADMIN_AUTHOR,
    )

    with respx.mock:
        respx.put(f"{_OPA_BASE}/v1/policies/_rego_validation_{POLICY_NAME}").mock(
            return_value=httpx.Response(200, json={})
        )
        respx.delete(f"{_OPA_BASE}/v1/policies/_rego_validation_{POLICY_NAME}").mock(
            return_value=httpx.Response(200)
        )
        push_route = respx.put(f"{_OPA_BASE}/v1/policies/{POLICY_NAME}").mock(
            return_value=httpx.Response(200, json={})
        )

        async with httpx.AsyncClient() as client:
            svc = PolicyService(
                repository=repo,
                validator=RegoValidator(client=client, opa_base=_OPA_BASE),
                opa_client=client,
                opa_base=_OPA_BASE,
            )
            resp = await svc.activate(policy_id=record.id)

    assert resp.bundle_push_ok is True
    assert push_route.called
    body_sent = push_route.calls[0].request.content.decode()
    assert "allow" in body_sent


@pytest.mark.asyncio
async def test_rollback_restores_previous_version(async_session) -> None:
    """AC-4: rollback to version 1.0.0 when 1.1.0 is active."""
    from datetime import datetime, timezone

    from tests.governance.conftest import VALID_REGO, ADMIN_AUTHOR

    repo = PolicyRepository(async_session)
    v1 = await repo.create(
        policy_group="grp3",
        version="1.0.0",
        description="",
        rego_body=VALID_REGO,
        author=ADMIN_AUTHOR,
    )
    await repo.set_active(policy_id=v1.id, activated_at=datetime.now(tz=timezone.utc))

    v2 = await repo.create(
        policy_group="grp3",
        version="1.1.0",
        description="",
        rego_body=VALID_REGO,
        author=ADMIN_AUTHOR,
    )
    await repo.set_active(policy_id=v2.id, activated_at=datetime.now(tz=timezone.utc))

    with respx.mock:
        respx.put(f"{_OPA_BASE}/v1/policies/_rego_validation_grp3").mock(
            return_value=httpx.Response(200, json={})
        )
        respx.delete(f"{_OPA_BASE}/v1/policies/_rego_validation_grp3").mock(
            return_value=httpx.Response(200)
        )
        respx.put(f"{_OPA_BASE}/v1/policies/grp3").mock(
            return_value=httpx.Response(200, json={})
        )

        async with httpx.AsyncClient() as client:
            svc = PolicyService(
                repository=repo,
                validator=RegoValidator(client=client, opa_base=_OPA_BASE),
                opa_client=client,
                opa_base=_OPA_BASE,
            )
            result = await svc.rollback(policy_group="grp3", target_version="1.0.0")

    assert result.restored_version == "1.0.0"
    assert result.previous_active == "1.1.0"

    versions = await repo.list_versions("grp3")
    statuses = {r.version: r.status for r in versions}
    assert statuses["1.0.0"] == PolicyStatus.ACTIVE
    assert statuses["1.1.0"] == PolicyStatus.ROLLED_BACK


@pytest.mark.asyncio
async def test_author_and_activated_at_stored(async_session) -> None:
    """AC-5: after activation, author is set from JWT sub and activated_at is not null."""
    from tests.governance.conftest import VALID_REGO, POLICY_NAME, ADMIN_AUTHOR

    repo = PolicyRepository(async_session)
    record = await repo.create(
        policy_group="audit_grp",
        version="1.0.0",
        description="",
        rego_body=VALID_REGO,
        author=ADMIN_AUTHOR,
    )

    with respx.mock:
        respx.put(f"{_OPA_BASE}/v1/policies/_rego_validation_audit_grp").mock(
            return_value=httpx.Response(200, json={})
        )
        respx.delete(f"{_OPA_BASE}/v1/policies/_rego_validation_audit_grp").mock(
            return_value=httpx.Response(200)
        )
        respx.put(f"{_OPA_BASE}/v1/policies/audit_grp").mock(
            return_value=httpx.Response(200, json={})
        )
        async with httpx.AsyncClient() as client:
            svc = PolicyService(
                repository=repo,
                validator=RegoValidator(client=client, opa_base=_OPA_BASE),
                opa_client=client,
                opa_base=_OPA_BASE,
            )
            await svc.activate(policy_id=record.id)

    updated = await repo.get_by_id(record.id)
    assert updated.author == ADMIN_AUTHOR
    assert updated.activated_at is not None
