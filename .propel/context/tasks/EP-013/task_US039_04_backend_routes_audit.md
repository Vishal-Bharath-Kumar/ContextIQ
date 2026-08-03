# TASK-US039-04 — Backend: Health-Check Route and Connector Audit Trail

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US039-04 |
| User Story | US-039 |
| Epic | EP-013 — Administration Portal |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Add the `POST /v1/knowledge-sources/{id}/health-check` route that triggers a live `health_check()` call against the connector (AC-3), and implement the `ConnectorAuditLog` ORM + `AuditRepository` that records every mutating connector event — create, status change, configuration update, and health-check result — in the audit trail (AC-5). Audit entries are appended to every existing mutating route in `knowledge_source_router.py`.

## Implementation Details

**Technology:** Python 3.11+, FastAPI, SQLAlchemy 2.x async, Alembic, Pydantic v2

**File locations:**
- `src/knowledge_sources/models/connector_audit_log.py` — `ConnectorAuditLog` ORM
- `src/knowledge_sources/schemas/connector_audit.py` — `AuditEventType`, `AuditEntry`, `HealthCheckResponse`
- `src/knowledge_sources/repositories/audit_repository.py` — `AuditRepository`
- `src/knowledge_sources/services/health_check_service.py` — `HealthCheckService`
- `src/knowledge_sources/routers/knowledge_source_router.py` — extend with health-check route + audit calls
- `alembic/versions/0016_create_connector_audit_log.py` — migration (follows `0015_create_execution_traces`)

---

### Pydantic schemas

```python
# src/knowledge_sources/schemas/connector_audit.py
from __future__ import annotations
from enum      import StrEnum
from uuid      import UUID
from datetime  import datetime
from pydantic  import BaseModel, ConfigDict


class AuditEventType(StrEnum):
    CREATED        = "created"
    STATUS_CHANGED = "status_changed"
    CONFIG_UPDATED = "config_updated"
    HEALTH_CHECKED = "health_checked"


class AuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    connector_id:  UUID
    event_type:    AuditEventType
    actor_user_id: str         # sub claim from JWT
    detail:        str | None  # human-readable summary, e.g. "status: active → inactive"


class HealthCheckResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok:         bool
    latency_ms: int
    detail:     str | None    # error description when ok=False
```

---

### `ConnectorAuditLog` ORM + Alembic migration

```python
# src/knowledge_sources/models/connector_audit_log.py
from __future__ import annotations
import uuid
from datetime       import datetime, timezone
from sqlalchemy     import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base    import Base


class ConnectorAuditLog(Base):
    __tablename__ = "connector_audit_log"

    id:            Mapped[uuid.UUID]  = mapped_column(primary_key=True, default=uuid.uuid4)
    connector_id:  Mapped[uuid.UUID]  = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    event_type:    Mapped[str]        = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[str]        = mapped_column(String(256), nullable=False)
    detail:        Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at:    Mapped[datetime]   = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

```python
# alembic/versions/0016_create_connector_audit_log.py
"""create connector_audit_log

Revision ID: 0016
Revises:     0015
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    op.create_table(
        "connector_audit_log",
        sa.Column("id",            sa.UUID(),      primary_key=True),
        sa.Column("connector_id",  sa.UUID(),      sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type",    sa.String(64),  nullable=False),
        sa.Column("actor_user_id", sa.String(256), nullable=False),
        sa.Column("detail",        sa.Text(),      nullable=True),
        sa.Column("created_at",    sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_connector_audit_log_connector_id", "connector_audit_log", ["connector_id"])


def downgrade() -> None:
    op.drop_index("ix_connector_audit_log_connector_id")
    op.drop_table("connector_audit_log")
```

---

### `AuditRepository`

```python
# src/knowledge_sources/repositories/audit_repository.py
from sqlalchemy.ext.asyncio import AsyncSession
from src.knowledge_sources.models.connector_audit_log import ConnectorAuditLog
from src.knowledge_sources.schemas.connector_audit    import AuditEntry


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(self, entry: AuditEntry) -> None:
        record = ConnectorAuditLog(
            connector_id  = entry.connector_id,
            event_type    = entry.event_type,
            actor_user_id = entry.actor_user_id,
            detail        = entry.detail,
        )
        self._session.add(record)
        await self._session.flush()   # write within current transaction; commit by caller
```

---

### `HealthCheckService`

```python
# src/knowledge_sources/services/health_check_service.py
from __future__ import annotations
import time
import importlib
from uuid   import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_sources.repositories.knowledge_source_repository import KnowledgeSourceRepository
from src.knowledge_sources.schemas.connector_audit                   import HealthCheckResponse
from fastapi                                                          import HTTPException, status


class HealthCheckService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = KnowledgeSourceRepository(session)

    async def run(self, source_id: UUID) -> HealthCheckResponse:
        record = await self._repo.get_by_id(source_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

        # Dynamically resolve the connector implementation by type
        # e.g. connector_type="github" → src.connectors.github.connector.GitHubConnector
        try:
            module     = importlib.import_module(f"src.connectors.{record.connector_type}.connector")
            cls        = getattr(module, f"{record.connector_type.capitalize()}Connector")
            connector  = cls(vault_path=record.vault_path, scope=record.scope)
        except (ImportError, AttributeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=f"Connector type '{record.connector_type}' not implemented",
            ) from exc

        t0 = time.monotonic()
        try:
            await connector.health_check()
            latency_ms = int((time.monotonic() - t0) * 1000)
            return HealthCheckResponse(ok=True, latency_ms=latency_ms, detail=None)
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return HealthCheckResponse(ok=False, latency_ms=latency_ms, detail=str(exc))
```

---

### Extend `knowledge_source_router.py`

```python
# src/knowledge_sources/routers/knowledge_source_router.py  (extend — add to existing router)
from uuid import UUID
from src.knowledge_sources.schemas.connector_audit        import AuditEntry, AuditEventType, HealthCheckResponse
from src.knowledge_sources.repositories.audit_repository  import AuditRepository
from src.knowledge_sources.services.health_check_service  import HealthCheckService
from src.gateway.middleware.auth                          import get_current_user


# Dependency for audit repository
async def get_audit_repo(
    session: AsyncSession = Depends(get_async_session),
) -> AuditRepository:
    return AuditRepository(session)


@router.post(
    "/{source_id}/health-check",
    response_model = HealthCheckResponse,
    summary        = "Test live connectivity for a connector (AC-3)",
)
async def health_check_connector(
    source_id:   UUID,
    session:     AsyncSession     = Depends(get_async_session),
    audit_repo:  AuditRepository  = Depends(get_audit_repo),
    current_user = Depends(get_current_user),
) -> HealthCheckResponse:
    svc    = HealthCheckService(session)
    result = await svc.run(source_id)

    await audit_repo.log(AuditEntry(
        connector_id  = source_id,
        event_type    = AuditEventType.HEALTH_CHECKED,
        actor_user_id = current_user.sub,
        detail        = f"ok={result.ok} latency_ms={result.latency_ms}",
    ))
    await session.commit()
    return result


# Extend existing PATCH /status route to emit audit entry (AC-5)
@router.patch(
    "/{source_id}/status",
    status_code = 200,
    summary     = "Enable or disable a connector (AC-4)",
)
async def update_connector_status(
    source_id:   UUID,
    body:        StatusUpdateRequest,            # existing schema — { status: "active"|"inactive" }
    service:     KnowledgeSourceService  = Depends(get_knowledge_source_service),
    audit_repo:  AuditRepository         = Depends(get_audit_repo),
    current_user = Depends(get_current_user),
) -> KnowledgeSourceResponse:
    result = await service.set_status(source_id, body.status)

    await audit_repo.log(AuditEntry(
        connector_id  = source_id,
        event_type    = AuditEventType.STATUS_CHANGED,
        actor_user_id = current_user.sub,
        detail        = f"status → {body.status}",
    ))
    await service.session.commit()
    return result
```

---

### Audit in POST `/v1/knowledge-sources` (creation)

```python
# knowledge_source_router.py  (extend existing POST handler — add audit call)
    await audit_repo.log(AuditEntry(
        connector_id  = created.id,
        event_type    = AuditEventType.CREATED,
        actor_user_id = current_user.sub,
        detail        = f"type={created.connector_type} scope={created.scope}",
    ))
    await session.commit()
```

## Acceptance Criteria

- [ ] `POST /v1/knowledge-sources/{id}/health-check` returns `{"ok": true, "latency_ms": N}` when the connector is reachable (AC-3)
- [ ] When connector raises an exception, `{"ok": false, "latency_ms": N, "detail": "..."}` is returned — HTTP 200, not 5xx (AC-3)
- [ ] A row is inserted into `connector_audit_log` for every `POST` (created), `PATCH /status` (status_changed), and `POST /health-check` (health_checked) call (AC-5)
- [ ] `actor_user_id` in the audit row equals the `sub` claim from the admin JWT
- [ ] Alembic migration `0016` creates `connector_audit_log` with FK to `knowledge_sources.id`
- [ ] `PATCH /v1/knowledge-sources/{id}/status` changes take effect immediately in the DB (status reflects within the next polling cycle — backend side of the 30 s SLA) (AC-4)

## Dependencies

- US-025 TASK-US025-03 — `KnowledgeSourceRepository` used by `HealthCheckService`
- US-025 TASK-US025-04 — `knowledge_source_router.py` extended (not rewritten)
- Connector implementations (`src/connectors/{type}/connector.py`) must expose `async health_check()`

## Definition of Done

- [ ] Alembic `upgrade head` runs without error
- [ ] `mypy --strict` passes; no `ruff` lint errors
- [ ] pytest tests: health-check success and failure paths, audit row inserted after each mutating call
