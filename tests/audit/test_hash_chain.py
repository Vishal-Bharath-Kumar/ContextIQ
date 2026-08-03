"""
AC-6: SHA-256 hash chain integrity unit tests.

Pure unit tests — no DB, no HTTP, no external dependencies.
Verifies compute_row_hash(), GENESIS_PREV_HASH, and row_fields_for_hashing()
behave as specified.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.audit.admin_audit_log.hash_chain import (
    GENESIS_PREV_HASH,
    compute_row_hash,
    row_fields_for_hashing,
)


class TestHashChain:
    """AC-6: SHA-256 chain integrity tests."""

    def _fields(self, action: str = "policy.created") -> dict:
        return row_fields_for_hashing(
            action=action,
            resource_type="policy",
            resource_id="pol-001",
            actor_user_id="user-001",
            ip_address="10.0.0.1",
            before_state=None,
            after_state={"name": "test"},
            timestamp=datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc),
        )

    def test_genesis_hash_is_deterministic(self) -> None:
        """Same inputs always produce the same 64-char hex digest."""
        h1 = compute_row_hash(GENESIS_PREV_HASH, self._fields())
        h2 = compute_row_hash(GENESIS_PREV_HASH, self._fields())
        assert h1 == h2
        assert len(h1) == 64, "SHA-256 hex digest must be 64 characters"

    def test_different_prev_hash_produces_different_row_hash(self) -> None:
        """Changing prev_hash changes the resulting row_hash."""
        h1 = compute_row_hash(GENESIS_PREV_HASH, self._fields())
        h2 = compute_row_hash("a" * 64, self._fields())
        assert h1 != h2

    def test_tampered_field_produces_different_hash(self) -> None:
        """Changing any auditable field changes the resulting row_hash."""
        h_base    = compute_row_hash(GENESIS_PREV_HASH, self._fields())
        h_tampered = compute_row_hash(GENESIS_PREV_HASH, self._fields(action="tampered.action"))
        assert h_base != h_tampered

    def test_chain_of_three_rows(self) -> None:
        """
        Verify a 3-row chain: each row's hash is the next row's prev_hash.

        Re-deriving any hash from its inputs must reproduce the original value.
        All three hashes must be distinct.
        """
        h0 = GENESIS_PREV_HASH
        h1 = compute_row_hash(h0, self._fields("policy.created"))
        h2 = compute_row_hash(h1, self._fields("policy.activated"))
        h3 = compute_row_hash(h2, self._fields("policy.rolled_back"))

        # Re-derivation must be idempotent
        assert compute_row_hash(h0, self._fields("policy.created")) == h1
        # All three digests must be distinct (no accidental collisions in test data)
        assert len({h1, h2, h3}) == 3
