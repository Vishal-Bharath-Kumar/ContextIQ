"""Unit tests for PolicyRepository — TASK-US033-02.

Uses a mocked AsyncSession so no real database is needed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.governance.policy.models import PolicyRecord
from src.governance.policy.repository import PolicyNotFoundError, PolicyRepository
from src.governance.policy.schemas import PolicyStatus

# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #


def _make_record(
    *,
    policy_group: str = "acl",
    version: str = "1.0.0",
    status: PolicyStatus = PolicyStatus.DRAFT,
    policy_id: uuid.UUID | None = None,
) -> PolicyRecord:
    record = MagicMock(spec=PolicyRecord)
    record.id = policy_id or uuid.uuid4()
    record.policy_group = policy_group
    record.version = version
    record.status = status
    record.activated_at = None
    return record


def _make_session(scalar_return=None, scalars_return=None) -> AsyncMock:
    """Return a minimal AsyncSession mock."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_return
    result.scalars.return_value.all.return_value = scalars_return or []
    session.execute.return_value = result
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


# ------------------------------------------------------------------ #
# create()                                                            #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_create_inserts_draft_record():
    session = _make_session()
    repo = PolicyRepository(session)

    record = await repo.create(
        policy_group="acl",
        version="1.0.0",
        description="First policy",
        rego_body="package acl\nallow = true",
        author="alice",
    )

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert record.status == PolicyStatus.DRAFT


@pytest.mark.asyncio
async def test_create_does_not_overwrite_existing(monkeypatch):
    """create() always inserts a new row; it does not do an UPDATE."""
    session = _make_session()
    repo = PolicyRepository(session)

    await repo.create(
        policy_group="acl",
        version="1.0.0",
        description="v1",
        rego_body="package acl",
        author="alice",
    )
    await repo.create(
        policy_group="acl",
        version="2.0.0",
        description="v2",
        rego_body="package acl\nallow = true",
        author="alice",
    )

    assert session.add.call_count == 2
    assert session.flush.await_count == 2


# ------------------------------------------------------------------ #
# list_versions()                                                     #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_list_versions_returns_all_rows():
    r1 = _make_record(version="1.0.0")
    r2 = _make_record(version="2.0.0")
    session = _make_session(scalars_return=[r2, r1])
    repo = PolicyRepository(session)

    versions = await repo.list_versions("acl")

    assert len(versions) == 2
    assert versions[0].version == "2.0.0"
    assert versions[1].version == "1.0.0"


@pytest.mark.asyncio
async def test_list_versions_returns_empty_for_unknown_group():
    session = _make_session(scalars_return=[])
    repo = PolicyRepository(session)

    versions = await repo.list_versions("unknown_group")

    assert versions == []


# ------------------------------------------------------------------ #
# set_active()                                                        #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_set_active_marks_record_active_and_supersedes_previous():
    target_id = uuid.uuid4()
    target = _make_record(policy_id=target_id, status=PolicyStatus.DRAFT)

    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = target
    session.execute.return_value = execute_result
    session.flush = AsyncMock()

    repo = PolicyRepository(session)
    now = datetime.now(timezone.utc)
    result = await repo.set_active(policy_id=target_id, activated_at=now)

    assert result.status == PolicyStatus.ACTIVE
    assert result.activated_at == now
    # execute called twice: once for get_by_id, once for the supersede UPDATE
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_set_active_raises_if_policy_not_found():
    session = _make_session(scalar_return=None)
    repo = PolicyRepository(session)

    with pytest.raises(PolicyNotFoundError):
        await repo.set_active(
            policy_id=uuid.uuid4(),
            activated_at=datetime.now(timezone.utc),
        )


# ------------------------------------------------------------------ #
# set_rolled_back()                                                   #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_set_rolled_back_demotes_active_and_promotes_target():
    current_id = uuid.uuid4()
    target_id = uuid.uuid4()
    current = _make_record(policy_id=current_id, status=PolicyStatus.ACTIVE)
    target = _make_record(policy_id=target_id, status=PolicyStatus.SUPERSEDED)

    call_count = 0

    async def _execute(stmt, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = current
        else:
            result.scalar_one_or_none.return_value = target
        return result

    session = AsyncMock()
    session.execute.side_effect = _execute
    session.flush = AsyncMock()

    repo = PolicyRepository(session)
    now = datetime.now(timezone.utc)
    result = await repo.set_rolled_back(
        current_active_id=current_id,
        target_version_id=target_id,
        activated_at=now,
    )

    assert current.status == PolicyStatus.ROLLED_BACK
    assert result.status == PolicyStatus.ACTIVE
    assert result.activated_at == now


@pytest.mark.asyncio
async def test_set_rolled_back_raises_if_current_not_found():
    session = _make_session(scalar_return=None)
    repo = PolicyRepository(session)

    with pytest.raises(PolicyNotFoundError):
        await repo.set_rolled_back(
            current_active_id=uuid.uuid4(),
            target_version_id=uuid.uuid4(),
            activated_at=datetime.now(timezone.utc),
        )


# ------------------------------------------------------------------ #
# get_active() / get_by_id() / get_version()                         #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_get_active_returns_active_record():
    record = _make_record(status=PolicyStatus.ACTIVE)
    session = _make_session(scalar_return=record)
    repo = PolicyRepository(session)

    result = await repo.get_active("acl")

    assert result is record


@pytest.mark.asyncio
async def test_get_active_returns_none_when_no_active():
    session = _make_session(scalar_return=None)
    repo = PolicyRepository(session)

    result = await repo.get_active("acl")

    assert result is None


@pytest.mark.asyncio
async def test_get_by_id_returns_record():
    policy_id = uuid.uuid4()
    record = _make_record(policy_id=policy_id)
    session = _make_session(scalar_return=record)
    repo = PolicyRepository(session)

    result = await repo.get_by_id(policy_id)

    assert result is record


@pytest.mark.asyncio
async def test_get_version_returns_matching_record():
    record = _make_record(version="1.0.0")
    session = _make_session(scalar_return=record)
    repo = PolicyRepository(session)

    result = await repo.get_version("acl", "1.0.0")

    assert result is record


# ------------------------------------------------------------------ #
# TASK-US033-05 — AC-2: version retention integration tests          #
# (backed by in-memory SQLite via async_session from conftest.py)    #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_all_versions_retained_on_create(async_session):
    """AC-2: Creating v1.1.0 does not delete v1.0.0."""
    from tests.governance.conftest import VALID_REGO, ADMIN_AUTHOR

    repo = PolicyRepository(async_session)
    await repo.create(
        policy_group="grp",
        version="1.0.0",
        description="",
        rego_body=VALID_REGO,
        author=ADMIN_AUTHOR,
    )
    await repo.create(
        policy_group="grp",
        version="1.1.0",
        description="",
        rego_body=VALID_REGO,
        author=ADMIN_AUTHOR,
    )

    versions = await repo.list_versions("grp")
    version_strs = [r.version for r in versions]
    assert "1.0.0" in version_strs
    assert "1.1.0" in version_strs
    assert len(versions) == 2


@pytest.mark.asyncio
async def test_activate_supersedes_prior_active(async_session):
    """AC-2: Activating v1.1.0 sets v1.0.0 to superseded — it is not deleted."""
    from datetime import datetime, timezone

    from tests.governance.conftest import VALID_REGO, ADMIN_AUTHOR

    repo = PolicyRepository(async_session)
    v1 = await repo.create(
        policy_group="grp2",
        version="1.0.0",
        description="",
        rego_body=VALID_REGO,
        author=ADMIN_AUTHOR,
    )
    await repo.set_active(policy_id=v1.id, activated_at=datetime.now(tz=timezone.utc))

    v2 = await repo.create(
        policy_group="grp2",
        version="1.1.0",
        description="",
        rego_body=VALID_REGO,
        author=ADMIN_AUTHOR,
    )
    await repo.set_active(policy_id=v2.id, activated_at=datetime.now(tz=timezone.utc))

    versions = await repo.list_versions("grp2")
    statuses = {r.version: r.status for r in versions}
    assert statuses["1.0.0"] == PolicyStatus.SUPERSEDED
    assert statuses["1.1.0"] == PolicyStatus.ACTIVE
