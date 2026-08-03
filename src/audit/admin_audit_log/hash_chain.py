"""
AC-6: tamper-evident SHA-256 hash chain for the admin audit log.

Each audit row stores:

    row_hash = SHA-256( prev_hash || row_canonical_json )

where ``||`` is string concatenation and ``row_canonical_json`` is the
JSON serialisation of the row's auditable fields, sorted by key.

The genesis hash (very first row ever inserted) uses the sentinel:

    GENESIS_PREV_HASH = "000...0"  (64 zeros)

Verification procedure:
  1. Read all rows ordered by insertion sequence (timestamp + id).
  2. For each row, re-compute the hash from the stored fields and the
     *previous* row's ``row_hash`` (or ``GENESIS_PREV_HASH`` for row 0).
  3. Compare re-computed hash with the stored ``row_hash``.
  4. Any mismatch indicates tampering or out-of-order insertion.

``row_fields_for_hashing()`` defines the STABLE field set included in the
hash.  This set must never change after the first row is inserted, because
any change would invalidate all existing hash verifications.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

#: Sentinel used as the ``prev_hash`` for the first row ever inserted.
#: 64 zero characters = 256 zero bits; chosen to be unambiguously distinct
#: from any real SHA-256 digest.
GENESIS_PREV_HASH: str = "0" * 64


def _canonical_json(row_fields: dict[str, Any]) -> str:
    """
    Deterministic JSON serialisation of audit row fields.

    - Keys sorted alphabetically (``sort_keys=True``)
    - No extra whitespace (``separators=(",", ":")``)
    - ``datetime`` objects serialised as UTC ISO-8601 strings
    """

    def _default(obj: Any) -> str:
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Non-serialisable type in audit hash input: {type(obj)!r}")

    return json.dumps(row_fields, sort_keys=True, separators=(",", ":"), default=_default)


def compute_row_hash(prev_hash: str, row_fields: dict[str, Any]) -> str:
    """
    Return the SHA-256 hex digest for a new audit row.

    Parameters
    ----------
    prev_hash:
        The ``row_hash`` of the immediately preceding row, or
        ``GENESIS_PREV_HASH`` for the very first row in the table.
    row_fields:
        Dict of auditable fields as returned by ``row_fields_for_hashing()``.
        Must NOT include ``row_hash`` itself (would create a circular dependency).

    Returns
    -------
    str
        64-character lowercase hex SHA-256 digest.
    """
    payload = prev_hash + _canonical_json(row_fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def row_fields_for_hashing(
    *,
    action:        str,
    resource_type: str,
    resource_id:   str,
    actor_user_id: str,
    ip_address:    str,
    before_state:  dict[str, Any] | None,
    after_state:   dict[str, Any] | None,
    timestamp:     datetime,
) -> dict[str, Any]:
    """
    Return the subset of fields included in the chain hash computation.

    STABILITY CONTRACT: This field set is frozen after the first row is
    inserted.  Adding, removing, or renaming any field breaks hash
    verification for all existing rows.  Any schema evolution must be
    handled by versioning (e.g. a new ``hash_version`` column + a new
    hash function).
    """
    return {
        "action":        action,
        "resource_type": resource_type,
        "resource_id":   resource_id,
        "actor_user_id": actor_user_id,
        "ip_address":    ip_address,
        "before_state":  before_state,
        "after_state":   after_state,
        "timestamp":     timestamp,
    }
