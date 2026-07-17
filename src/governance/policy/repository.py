"""PolicyRepository — async SQLAlchemy repository for policy_definitions.

Version retention rule (AC-2):
- Records are never deleted via this repository.
- Status transitions: draft → active (on activate); active → superseded (when
  newer version activated); active → rolled_back (on rollback).

Satisfies AC-1 (create draft), AC-2 (no deletes, all versions retained),
AC-3 (active status transition), AC-4 (rollback), AC-5 (audit query).
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.governance.policy.models import PolicyRecord
from src.governance.policy.schemas import PolicyStatus


class PolicyNotFoundError(Exception):
    """Raised when a policy record UUID does not exist in the database."""


class PolicyRepository:
    """Async repository for the policy_definitions table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Writes                                                               #
    # ------------------------------------------------------------------ #

    async def create(
        self,
        *,
        policy_group: str,
        version: str,
        description: str,
        rego_body: str,
        author: str,
    ) -> PolicyRecord:
        """Insert a new policy version in DRAFT status. AC-1, AC-2."""
        record = PolicyRecord(
            id=uuid.uuid4(),
            policy_group=policy_group,
            version=version,
            description=description,
            rego_body=rego_body,
            status=PolicyStatus.DRAFT,
            author=author,
            activated_at=None,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def set_active(
        self,
        *,
        policy_id: uuid.UUID,
        activated_at: datetime,
    ) -> PolicyRecord:
        """Mark policy_id as ACTIVE; supersede any previous active version.

        Called inside the same transaction by PolicyService (AC-3, AC-5).
        """
        record = await self._get_or_raise(policy_id)
        await self._session.execute(
            update(PolicyRecord)
            .where(
                PolicyRecord.policy_group == record.policy_group,
                PolicyRecord.status == PolicyStatus.ACTIVE,
                PolicyRecord.id != policy_id,
            )
            .values(status=PolicyStatus.SUPERSEDED)
        )
        record.status = PolicyStatus.ACTIVE
        record.activated_at = activated_at
        await self._session.flush()
        return record

    async def set_rolled_back(
        self,
        *,
        current_active_id: uuid.UUID,
        target_version_id: uuid.UUID,
        activated_at: datetime,
    ) -> PolicyRecord:
        """Demote current_active_id to ROLLED_BACK; promote target_version_id to ACTIVE.

        Returns the newly active record. AC-4.
        """
        current = await self._get_or_raise(current_active_id)
        current.status = PolicyStatus.ROLLED_BACK

        target = await self._get_or_raise(target_version_id)
        target.status = PolicyStatus.ACTIVE
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
                PolicyRecord.status == PolicyStatus.ACTIVE,
            )
        )
        return result.scalar_one_or_none()

    async def list_versions(self, policy_group: str) -> Sequence[PolicyRecord]:
        """Return all versions for a policy_group in descending created_at order.

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
                PolicyRecord.version == version,
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
