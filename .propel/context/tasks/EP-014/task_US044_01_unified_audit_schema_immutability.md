# TASK-US044-01 — Unified `admin_audit_log` Schema, Immutability, and SHA-256 Chain

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US044-01 |
| User Story | US-044 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Define the single `AdminAuditLog` ORM table that records every mutating Admin API action across all domains — policy, connector, model, and role change (AC-1). Enforce row-level immutability at the PostgreSQL layer via a `BEFORE UPDATE OR DELETE` trigger that raises an exception (AC-2). Store a SHA-256 chain hash on every row so that the audit log's integrity can be independently verified without trusting the application layer (AC-6). The Alembic migration is revision `0019` (follows `0018_create_model_audit_log`).

## Implementation Details

**Technology:** Python 3.11+, SQLAlchemy 2.x async, Alembic, PostgreSQL 15, Pydantic v2

**File locations:**
- `src/audit/admin_audit_log/models.py` — `AdminAuditLog` ORM
- `src/audit/admin_audit_log/schemas.py` — `AdminActionType`, `AuditLogEntry`, `AuditLogCreateRequest`
- `src/audit/admin_audit_log/hash_chain.py` — SHA-256 chain hash computation
- `alembic/versions/0019_create_admin_audit_log.py`

---

### `AdminActionType` enum and Pydantic schemas

```python
# src/audit/admin_audit_log/schemas.py
from __future__ import annotations
from enum      import StrEnum
from uuid      import UUID
from datetime  import datetime
from typing    import Any
from pydantic  import BaseModel, ConfigDict, Field


class AdminActionType(StrEnum):
    # Policy lifecycle
    POLICY_CREATED          = "policy.created"
    POLICY_ACTIVATED        = "policy.activated"
    POLICY_ROLLED_BACK      = "policy.rolled_back"
    POLICY_DELETED          = "policy.deleted"

    # Connector lifecycle
    CONNECTOR_CREATED       = "connector.created"
    CONNECTOR_UPDATED       = "connector.updated"
    CONNECTOR_STATUS_CHANGED = "connector.status_changed"
    CONNECTOR_DELETED       = "connector.deleted"

    # Model registry
    MODEL_REGISTERED        = "model.registered"
    MODEL_STATUS_CHANGED    = "model.status_changed"
    MODEL_WEIGHTS_UPDATED   = "model.weights_updated"

    # RBAC / identity
    ROLE_ASSIGNED           = "role.assigned"
    ROLE_REVOKED            = "role.revoked"


class AuditLogCreateRequest(BaseModel):
    """Passed by route handlers to `AdminAuditRepository.log()`."""
    model_config = ConfigDict(frozen=True)

    action:        AdminActionType
    resource_type: str              # e.g. "policy", "connector", "model"
    resource_id:   str              # string to handle both UUID and string IDs
    actor_user_id: str              # JWT `sub` claim
    ip_address:    str              # from request.client.host (X-Forwarded-For preferred)
    before_state:  dict[str, Any] | None = None   # JSON snapshot before mutation
    after_state:   dict[str, Any] | None = None   # JSON snapshot after mutation


class AuditLogEntry(BaseModel):
    """API response DTO."""
    model_config = ConfigDict(frozen=True)

    id:            UUID
    action:        AdminActionType
    resource_type: str
    resource_id:   str
    actor_user_id: str
    ip_address:    str
    before_state:  dict[str, Any] | None
    after_state:   dict[str, Any] | None
    timestamp:     datetime
    row_hash:      str    # SHA-256 of this row's content + previous row's hash (AC-6)
```

---

### SHA-256 chain hash

```python
# src/audit/admin_audit_log/hash_chain.py
"""
AC-6: tamper-evident hash chain.

Each audit row stores:
    row_hash = SHA-256( prev_hash || row_canonical_json )

where `||` is string concatenation and `row_canonical_json` is the
JSON serialisation of the row's auditable fields, sorted by key.

The genesis hash (first ever row) uses the sentinel:
    GENESIS_PREV_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

Verification re-computes every row's hash and compares to the stored value.
Any mismatch indicates tampering or out-of-order insertion.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime
from typing   import Any

GENESIS_PREV_HASH = "0" * 64


def _canonical_json(row_fields: dict[str, Any]) -> str:
    """Deterministic JSON: sort keys, no extra whitespace, UTC ISO timestamps."""

    def _default(obj: Any) -> str:
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Non-serialisable type: {type(obj)}")

    return json.dumps(row_fields, sort_keys=True, separators=(",", ":"), default=_default)


def compute_row_hash(prev_hash: str, row_fields: dict[str, Any]) -> str:
    """
    Returns the SHA-256 hex digest for a new audit row.

    Args:
        prev_hash:  The `row_hash` of the immediately preceding row,
                    or `GENESIS_PREV_HASH` for the very first row.
        row_fields: Dict of auditable fields — must NOT include `row_hash` itself.
    """
    canonical = prev_hash + _canonical_json(row_fields)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    Returns the subset of fields included in the hash computation.
    Kept stable — adding new fields would break existing hash verification.
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
```

---

### `AdminAuditLog` ORM

```python
# src/audit/admin_audit_log/models.py
from __future__ import annotations
import uuid
from datetime       import datetime, timezone
from typing         import Any
from sqlalchemy     import String, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base    import Base


class AdminAuditLog(Base):
    """
    AC-1: unified audit log for all mutating Admin API actions.
    AC-2: row-level immutability enforced via PostgreSQL trigger (see migration).
    AC-6: SHA-256 hash chain stored in `row_hash`.

    IMPORTANT: this table must NEVER be truncated, updated, or have rows deleted
    by application code. The database-level trigger is the final enforcement layer.
    """
    __tablename__ = "admin_audit_log"

    id:            Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    action:        Mapped[str]              = mapped_column(String(64),  nullable=False, index=True)
    resource_type: Mapped[str]              = mapped_column(String(64),  nullable=False, index=True)
    resource_id:   Mapped[str]              = mapped_column(String(256), nullable=False, index=True)
    actor_user_id: Mapped[str]              = mapped_column(String(256), nullable=False, index=True)
    ip_address:    Mapped[str]              = mapped_column(String(64),  nullable=False)
    before_state:  Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_state:   Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    timestamp:     Mapped[datetime]         = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    # AC-6: hash of this row's content + previous row's hash
    row_hash:      Mapped[str]              = mapped_column(String(64),  nullable=False)
```

---

### Alembic migration with immutability trigger

```python
# alembic/versions/0019_create_admin_audit_log.py
"""create admin_audit_log with immutability trigger

Revision ID: 0019
Revises:     0018
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision      = "0019"
down_revision = "0018"

_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION admin_audit_log_immutability()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'admin_audit_log rows are immutable: UPDATE and DELETE are not permitted';
END;
$$;
"""

_TRIGGER = """
CREATE TRIGGER trg_admin_audit_log_immutable
BEFORE UPDATE OR DELETE ON admin_audit_log
FOR EACH ROW EXECUTE FUNCTION admin_audit_log_immutability();
"""


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id",            sa.UUID(),                  primary_key=True),
        sa.Column("action",        sa.String(64),              nullable=False),
        sa.Column("resource_type", sa.String(64),              nullable=False),
        sa.Column("resource_id",   sa.String(256),             nullable=False),
        sa.Column("actor_user_id", sa.String(256),             nullable=False),
        sa.Column("ip_address",    sa.String(64),              nullable=False),
        sa.Column("before_state",  JSONB(),                    nullable=True),
        sa.Column("after_state",   JSONB(),                    nullable=True),
        sa.Column("timestamp",     sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("row_hash",      sa.String(64),              nullable=False),
    )
    op.create_index("ix_admin_audit_log_action",        "admin_audit_log", ["action"])
    op.create_index("ix_admin_audit_log_resource_type", "admin_audit_log", ["resource_type"])
    op.create_index("ix_admin_audit_log_resource_id",   "admin_audit_log", ["resource_id"])
    op.create_index("ix_admin_audit_log_actor_user_id", "admin_audit_log", ["actor_user_id"])
    op.create_index("ix_admin_audit_log_timestamp",     "admin_audit_log", ["timestamp"])

    # AC-2: immutability trigger — installed after table creation
    op.execute(_TRIGGER_FN)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_admin_audit_log_immutable ON admin_audit_log")
    op.execute("DROP FUNCTION IF EXISTS admin_audit_log_immutability")
    op.drop_table("admin_audit_log")
```

## Acceptance Criteria

- [ ] `AdminAuditLog` ORM has all AC-1 required fields: `user_id` (→ `actor_user_id`), `action`, `resource_type`, `resource_id`, `before_state`, `after_state`, `timestamp`, `ip_address` (AC-1)
- [ ] Alembic migration `0019` creates the table + the `trg_admin_audit_log_immutable` trigger (AC-2)
- [ ] `UPDATE admin_audit_log SET action='x' WHERE ...` raises `PL/pgSQL` exception — verifiable via `psql` or pytest (AC-2)
- [ ] `DELETE FROM admin_audit_log WHERE ...` raises the same exception (AC-2)
- [ ] `compute_row_hash()` is deterministic: same inputs always produce the same SHA-256 digest (AC-6)
- [ ] `GENESIS_PREV_HASH` is the sentinel for the first row in the table (AC-6)
- [ ] `row_fields_for_hashing()` is stable — its field list is documented as immutable (AC-6)

## Dependencies

- TASK-US042-01 — `AdminActionType` values align with RBAC-protected endpoints
- EP-DATA-001 — PostgreSQL 15 with `pgcrypto` extension available
- Alembic revision `0018_create_model_audit_log` must exist (down_revision reference)

## Definition of Done

- [ ] `alembic upgrade 0019` runs without error
- [ ] `psql -c "UPDATE admin_audit_log SET action='x' WHERE true"` returns error (immutability test)
- [ ] `mypy --strict src/audit/admin_audit_log/` passes
