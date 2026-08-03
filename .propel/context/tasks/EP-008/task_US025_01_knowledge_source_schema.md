# TASK-US025-01 — `KnowledgeSourceRecord` ORM, Pydantic Schemas, and Alembic Migration

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US025-01 |
| User Story | US-025 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Define the `knowledge_sources` PostgreSQL table, the SQLAlchemy 2.x async ORM model, the Alembic migration, and the Pydantic request/response schemas. This is the data foundation for every downstream EP-008 story (US-026, US-027) and the Admin API routes in TASK-US025-04.

## Implementation Details

**Technology:** Python 3.11+, SQLAlchemy 2.x async, Alembic, Pydantic v2, PostgreSQL 15

**File locations:**
- `src/knowledge_sources/models/knowledge_source.py` — `KnowledgeSourceRecord` ORM
- `src/knowledge_sources/schemas/knowledge_source.py` — `ConnectorType`, `SourceStatus`, `KnowledgeSourceCreate`, `KnowledgeSourceResponse`
- `alembic/versions/0011_create_knowledge_sources.py` — migration
- `tests/knowledge_sources/test_knowledge_source_orm.py`

**`ConnectorType` and `SourceStatus`:**

```python
# src/knowledge_sources/schemas/knowledge_source.py
from enum import StrEnum

class ConnectorType(StrEnum):
    GITHUB     = "github"
    CONFLUENCE = "confluence"
    JIRA       = "jira"
    GRAFANA    = "grafana"

class SourceStatus(StrEnum):
    ACTIVE   = "active"    # indexed and eligible for retrieval
    INACTIVE = "inactive"  # registered but excluded from retrieval
    SYNCING  = "syncing"   # sync job currently in progress
    ERROR    = "error"     # last sync failed
```

**`KnowledgeSourceCreate` — inbound API payload (US-025 AC-1):**

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re

class KnowledgeSourceCreate(BaseModel):
    connector_type:        ConnectorType
    credentials_vault_path: str = Field(
        min_length=1, max_length=512,
        description="Vault KV v2 path where connector credentials are stored",
    )
    scope:                 str = Field(
        min_length=1, max_length=1024,
        description="Connector-specific scope: 'owner/repo' for GitHub, 'SPACE' for Confluence, etc.",
    )
    sync_schedule:         str = Field(
        default="0 */6 * * *",
        description="Cron expression for scheduled sync (UTC). Default: every 6 hours.",
    )
    token_budget_weight:   float = Field(
        default=1.0, ge=0.0, le=10.0,
        description="Relative weight for token budget allocation across sources.",
    )

    @field_validator("sync_schedule")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError("sync_schedule must be a 5-field cron expression (e.g. '0 */6 * * *')")
        return v

    @field_validator("credentials_vault_path")
    @classmethod
    def validate_vault_path_format(cls, v: str) -> str:
        """Structural check only — live Vault validation is in VaultPathValidator."""
        if not re.match(r'^[a-zA-Z0-9/_\-\.]+$', v):
            raise ValueError("credentials_vault_path contains invalid characters")
        return v
```

**`KnowledgeSourceResponse` — outbound API response (US-025 AC-3):**

```python
from datetime import datetime
from uuid import UUID

class KnowledgeSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:                    UUID
    connector_type:        ConnectorType
    credentials_vault_path: str
    scope:                 str
    sync_schedule:         str
    token_budget_weight:   float
    status:                SourceStatus
    is_active:             bool
    last_sync_at:          datetime | None
    document_count:        int
    created_at:            datetime
    updated_at:            datetime
```

**`KnowledgeSourceRecord` ORM:**

```python
# src/knowledge_sources/models/knowledge_source.py
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import String, Float, Boolean, Integer, Enum as PgEnum, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from src.db.base import Base

class KnowledgeSourceRecord(Base):
    __tablename__ = "knowledge_sources"

    id:                    Mapped[UUID]     = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    connector_type:        Mapped[str]      = mapped_column(
        PgEnum("github", "confluence", "jira", "grafana", name="connector_type_enum"), nullable=False
    )
    credentials_vault_path: Mapped[str]    = mapped_column(String(512), nullable=False)
    scope:                 Mapped[str]      = mapped_column(String(1024), nullable=False)
    sync_schedule:         Mapped[str]      = mapped_column(String(64), nullable=False, server_default="0 */6 * * *")
    token_budget_weight:   Mapped[float]    = mapped_column(Float, nullable=False, server_default=text("1.0"))
    status:                Mapped[str]      = mapped_column(
        PgEnum("active", "inactive", "syncing", "error", name="source_status_enum"),
        nullable=False, server_default="active",
    )
    is_active:             Mapped[bool]     = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_sync_at:          Mapped[datetime | None] = mapped_column(nullable=True)
    document_count:        Mapped[int]      = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at:            Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    updated_at:            Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"), onupdate=datetime.utcnow)
```

**Alembic migration `0011_create_knowledge_sources.py`:**

```python
def upgrade() -> None:
    op.execute("CREATE TYPE connector_type_enum AS ENUM ('github','confluence','jira','grafana')")
    op.execute("CREATE TYPE source_status_enum  AS ENUM ('active','inactive','syncing','error')")
    op.create_table(
        "knowledge_sources",
        sa.Column("id",                    postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("connector_type",        sa.Enum(name="connector_type_enum"), nullable=False),
        sa.Column("credentials_vault_path", sa.String(512), nullable=False),
        sa.Column("scope",                 sa.String(1024), nullable=False),
        sa.Column("sync_schedule",         sa.String(64),   nullable=False, server_default="0 */6 * * *"),
        sa.Column("token_budget_weight",   sa.Float(),      nullable=False, server_default="1.0"),
        sa.Column("status",                sa.Enum(name="source_status_enum"), nullable=False, server_default="active"),
        sa.Column("is_active",             sa.Boolean(),    nullable=False, server_default="true"),
        sa.Column("last_sync_at",          sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("document_count",        sa.Integer(),    nullable=False, server_default="0"),
        sa.Column("created_at",            sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at",            sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_knowledge_sources_connector_scope", "knowledge_sources", ["connector_type", "scope"], unique=True)
    op.create_index("idx_knowledge_sources_is_active",       "knowledge_sources", ["is_active"])

def downgrade() -> None:
    op.drop_table("knowledge_sources")
    op.execute("DROP TYPE IF EXISTS source_status_enum")
    op.execute("DROP TYPE IF EXISTS connector_type_enum")
```

**Unique constraint:** `(connector_type, scope)` pair is unique — prevents duplicate registrations of the same GitHub repo or Confluence space.

## Acceptance Criteria

- [ ] `KnowledgeSourceCreate` with all required fields validates successfully
- [ ] `KnowledgeSourceCreate` with a 6-field cron expression raises `ValidationError`
- [ ] `KnowledgeSourceCreate` with `token_budget_weight=10.1` raises `ValidationError` (`le=10.0`)
- [ ] `KnowledgeSourceCreate.credentials_vault_path` with spaces raises `ValidationError`
- [ ] `KnowledgeSourceResponse` populates `status`, `last_sync_at`, and `document_count` from ORM attributes
- [ ] Alembic `upgrade()` creates the table; `downgrade()` removes it cleanly

## Dependencies

- No upstream task dependencies — this is the data foundation for EP-008.
- Alembic version chain: follows `0010_create_model_registry` (TASK-US018-02)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Migration tested with `alembic upgrade head` and `alembic downgrade -1` in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
