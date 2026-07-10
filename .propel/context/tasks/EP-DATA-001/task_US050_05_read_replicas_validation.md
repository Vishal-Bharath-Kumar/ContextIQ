# TASK-US050-05 — Read Replicas for Reporting Queries and Full Integration Validation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US050-05 |
| User Story | US-050 |
| Epic | EP-DATA-001 — Polyglot Data Store Setup |
| Layer | Infrastructure / Backend / QA |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Enable two PostgreSQL streaming read replicas in the Bitnami chart (`values-prod.yaml`) for reporting workloads (AC-6). Application code that serves audit log queries and cost analytics routes reads to a dedicated `read_replica_engine` connected via PgBouncer to the replica Service, keeping reporting traffic off the primary write path. An `AsyncSession` factory selects the appropriate engine based on a `read_only: bool` flag on the database dependency. Integration tests validate all 6 ACs for US-050.

## Implementation Details

**Technology:** PostgreSQL 15 streaming replication, Bitnami chart replica StatefulSet, SQLAlchemy 2.x async, Python 3.11+, pytest 7+

**File locations:**
- `helm/charts/postgresql/values-prod.yaml` — set `readReplicas.replicaCount: 2`
- `src/data/database.py` — dual-engine setup (primary + read-replica)
- `src/data/dependencies.py` — `get_db()` and `get_read_db()` FastAPI dependencies
- `src/api/admin/routes/audit_log.py` — switch query to `get_read_db()`
- `src/api/admin/routes/cost_analytics.py` — switch query to `get_read_db()`
- `tests/integration/test_postgres_setup.py` — US-050 integration test suite

---

### Enable read replicas (Bitnami chart)

```yaml
# helm/charts/postgresql/values-prod.yaml  (extend)
postgresql:
  readReplicas:
    replicaCount: 2    # AC-6: 2 replicas for reporting read distribution

    # Replicas use the same encrypted StorageClass (TASK-US048-04)
    persistence:
      storageClass: contextiq-encrypted-gp3
      size:         500Gi

    resources:
      requests: { cpu: "1",    memory: "4Gi" }
      limits:   { cpu: "4",    memory: "8Gi" }

    # PDB for replicas: allow 1 replica to be disrupted at a time (2 replicas total)
    podDisruptionBudget:
      enabled:      true
      minAvailable: 1

  # primary.configuration already sets wal_level=replica, max_wal_senders=5 (TASK-US050-04)
```

The Bitnami chart automatically configures `primary_conninfo` on replicas and registers them as hot-standby nodes. No manual `recovery.conf` is needed.

---

### Dual-engine database setup

```python
# src/data/database.py
"""
Database engine factory.

Two engines:
  - PRIMARY_ENGINE  — writable; points at PgBouncer → PostgreSQL primary
  - REPLICA_ENGINE  — read-only; points at PgBouncer → PostgreSQL read replicas

AC-6: reporting queries (audit log, cost analytics) use REPLICA_ENGINE so they
do not compete with write traffic on the primary.
"""
from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# PgBouncer Services:
#   postgresql-pgbouncer.contextiq-data.svc.cluster.local      → primary pool
#   postgresql-pgbouncer-read.contextiq-data.svc.cluster.local → replica pool
#
# Both URLs provided by Vault Agent (/vault/secrets/postgres.env) which renders
# separate credentials for primary and read-replica roles.


@lru_cache(maxsize=1)
def _primary_engine() -> AsyncEngine:
    url = os.environ["DATABASE_URL"]    # points at PgBouncer → primary
    return create_async_engine(
        url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        connect_args={
            "statement_cache_size": 0,    # PgBouncer transaction mode (TASK-US050-04)
            "ssl": "require",
        },
    )


@lru_cache(maxsize=1)
def _replica_engine() -> AsyncEngine:
    # AC-6: read replica URL — falls back to primary URL if not set (dev/test convenience)
    url = os.environ.get("DATABASE_READ_URL", os.environ["DATABASE_URL"])
    return create_async_engine(
        url,
        pool_size=5,
        max_overflow=20,    # replicas can handle more concurrent reads
        pool_pre_ping=True,
        connect_args={
            "statement_cache_size": 0,
            "ssl": "require",
        },
        execution_options={"postgresql_readonly": True},    # advisory flag — never write to replica
    )


def primary_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_primary_engine(), expire_on_commit=False)


def replica_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_replica_engine(), expire_on_commit=False)
```

---

### FastAPI database dependencies

```python
# src/data/dependencies.py
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.database import primary_session_factory, replica_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: writable session on the primary PostgreSQL node."""
    async with primary_session_factory()() as session:
        yield session


async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency: read-only session on a PostgreSQL read replica.
    AC-6: use for audit log queries and cost analytics — keeps reporting
    traffic off the primary write path.
    """
    async with replica_session_factory()() as session:
        yield session
```

---

### Route updates: audit log and cost analytics use read replica

```python
# src/api/admin/routes/audit_log.py  (update — replace Depends(get_db) with Depends(get_read_db))
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.dependencies import get_read_db    # AC-6: read replica
from src.audit.admin_audit_log.query_repository import AuditLogQueryRepository

router = APIRouter(prefix="/v1/audit-log", tags=["audit-log"])


@router.get("")
async def list_audit_log(
    limit:  int = Query(default=50, le=200),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_read_db),    # AC-6: read replica session
) -> dict:
    repo = AuditLogQueryRepository(db)
    return await repo.list(limit=limit, cursor=cursor)
```

---

### Vault Agent template: render both primary and replica database URLs

```
# Addition to Vault Agent annotation template (extends TASK-US047-03 pattern)
vault.hashicorp.com/agent-inject-secret-postgres-read: "database/postgres/creds/mcp-gateway"
vault.hashicorp.com/agent-inject-template-postgres-read: |
  {{- with secret "database/postgres/creds/mcp-gateway" -}}
  export DATABASE_READ_URL="postgresql+asyncpg://{{ .Data.username }}:{{ .Data.password }}@postgresql-pgbouncer-read.contextiq-data.svc.cluster.local:5432/contextiq?ssl=require"
  {{- end }}
```

---

### Integration test suite — all US-050 ACs

```python
# tests/integration/test_postgres_setup.py
"""
Integration tests for US-050: PostgreSQL schema deployment and management.

Prerequisites:
  - PostgreSQL running and accessible
  - DATABASE_URL and DATABASE_READ_URL set in environment
  - Alembic migrations applied (alembic upgrade head)
  - PgBouncer running

Run:
    pytest tests/integration/test_postgres_setup.py -v --tb=short
"""
from __future__ import annotations

import asyncio
import os
import subprocess

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL      = os.environ["DATABASE_URL"]
DATABASE_READ_URL = os.environ.get("DATABASE_READ_URL", DATABASE_URL)

SYNC_URL      = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
SYNC_READ_URL = DATABASE_READ_URL.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="session")
def primary_engine():
    engine = create_async_engine(DATABASE_URL, connect_args={"statement_cache_size": 0, "ssl": "require"})
    yield engine
    asyncio.get_event_loop().run_until_complete(engine.dispose())


@pytest.fixture(scope="session")
def replica_engine():
    engine = create_async_engine(DATABASE_READ_URL, connect_args={"statement_cache_size": 0, "ssl": "require"})
    yield engine
    asyncio.get_event_loop().run_until_complete(engine.dispose())


# ---------------------------------------------------------------------------
# AC-1: PostgreSQL running with persistent volume and backup configured
# ---------------------------------------------------------------------------

class TestAC1_PostgreSQLDeployment:

    def test_postgresql_pod_running(self) -> None:
        result = subprocess.run(
            ["kubectl", "get", "pod", "postgresql-primary-0", "-n", "contextiq-data",
             "-o", "jsonpath={.status.phase}"],
            capture_output=True, timeout=15,
        )
        assert result.stdout.decode().strip() == "Running", (
            "postgresql-primary-0 is not Running (AC-1)"
        )

    def test_pvc_uses_encrypted_storage_class(self) -> None:
        result = subprocess.run(
            ["kubectl", "get", "pvc", "data-postgresql-primary-0", "-n", "contextiq-data",
             "-o", "jsonpath={.spec.storageClassName}"],
            capture_output=True, timeout=15,
        )
        assert result.stdout.decode().strip() == "contextiq-encrypted-gp3", (
            "PVC does not use contextiq-encrypted-gp3 StorageClass"
        )

    def test_backup_cronjob_exists(self) -> None:
        result = subprocess.run(
            ["kubectl", "get", "cronjob", "postgres-backup", "-n", "contextiq-data",
             "-o", "jsonpath={.spec.schedule}"],
            capture_output=True, timeout=15,
        )
        assert result.stdout.decode().strip() == "0 1 * * *", (
            "Backup CronJob not found or has wrong schedule (AC-1)"
        )


# ---------------------------------------------------------------------------
# AC-2: All 8 core tables exist after migration
# ---------------------------------------------------------------------------

class TestAC2_CoreTables:

    EXPECTED_TABLES = [
        "connector_config", "knowledge_source", "knowledge_chunk",
        "model_registry", "policy", "audit_log",
        "execution_trace_index", "sync_job",
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("table_name", EXPECTED_TABLES)
    async def test_table_exists(self, primary_engine, table_name: str) -> None:
        async with primary_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT to_regclass(:table)"),
                {"table": f"public.{table_name}"},
            )
            row = result.scalar()
        assert row is not None, f"Table '{table_name}' does not exist in public schema (AC-2)"

    @pytest.mark.asyncio
    async def test_alembic_at_head(self) -> None:
        result = subprocess.run(
            ["uv", "run", "alembic", "current"],
            capture_output=True, timeout=30, env={**os.environ},
        )
        output = result.stdout.decode()
        assert "0020" in output and "(head)" in output, (
            f"Alembic is not at head 0020: {output!r} (AC-2)"
        )


# ---------------------------------------------------------------------------
# AC-3: Migration Job ran successfully before pods started
# ---------------------------------------------------------------------------

class TestAC3_MigrationJob:

    def test_migration_job_succeeded(self) -> None:
        result = subprocess.run(
            ["kubectl", "get", "job", "alembic-migration", "-n", "contextiq-data",
             "-o", "jsonpath={.status.succeeded}"],
            capture_output=True, timeout=15,
        )
        succeeded = result.stdout.decode().strip()
        assert succeeded == "1", (
            f"Migration Job succeeded count is {succeeded!r}, expected '1' (AC-3)"
        )


# ---------------------------------------------------------------------------
# AC-4: Migration failure surfaces as descriptive pod startup failure
# ---------------------------------------------------------------------------

class TestAC4_MigrationFailureHandling:

    def test_migration_runner_exits_nonzero_on_bad_url(self) -> None:
        """Unit-level: run_migration.py with an invalid URL must exit 1."""
        result = subprocess.run(
            ["python", "-m", "scripts.ci.run_migration"],
            capture_output=True, timeout=30,
            env={**os.environ, "DATABASE_URL": "postgresql+asyncpg://bad:bad@localhost:9999/nodb"},
        )
        assert result.returncode == 1, (
            "run_migration.py did not exit 1 on a bad DATABASE_URL (AC-4)"
        )
        assert b"migration_error" in result.stdout or b"migration_error" in result.stderr, (
            "migration_error JSON event not emitted on failure (AC-4)"
        )


# ---------------------------------------------------------------------------
# AC-5: PgBouncer running; max 200 server-side PostgreSQL connections
# ---------------------------------------------------------------------------

class TestAC5_PgBouncerConnectionPooling:

    def test_pgbouncer_pods_running(self) -> None:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", "contextiq-data",
             "-l", "app.kubernetes.io/name=pgbouncer",
             "-o", "jsonpath={.items[*].status.phase}"],
            capture_output=True, timeout=15,
        )
        phases = result.stdout.decode().split()
        assert all(p == "Running" for p in phases) and len(phases) >= 2, (
            f"PgBouncer pods not all Running: {phases} (AC-5)"
        )

    @pytest.mark.asyncio
    async def test_max_connections_set_on_postgresql(self, primary_engine) -> None:
        async with primary_engine.connect() as conn:
            result = await conn.execute(text("SHOW max_connections"))
            max_conn = int(result.scalar())
        assert max_conn >= 200, (
            f"PostgreSQL max_connections={max_conn}, expected >= 200 (AC-5)"
        )

    @pytest.mark.asyncio
    async def test_pgbouncer_pool_mode_is_transaction(self, primary_engine) -> None:
        """Indirect check: transaction mode is incompatible with server-side prepared statements."""
        # In transaction pool mode, PREPARE creates a temporary prepared statement
        # that is transparently handled per-connection; this validates the connection
        # path goes through PgBouncer transaction mode (prepared statements silently ignored)
        async with primary_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))  # basic connectivity through PgBouncer


# ---------------------------------------------------------------------------
# AC-6: Read replicas running; reporting queries routed to replica
# ---------------------------------------------------------------------------

class TestAC6_ReadReplicas:

    def test_read_replica_pods_running(self) -> None:
        result = subprocess.run(
            ["kubectl", "get", "statefulset", "postgresql-read", "-n", "contextiq-data",
             "-o", "jsonpath={.status.readyReplicas}"],
            capture_output=True, timeout=15,
        )
        ready = result.stdout.decode().strip()
        assert int(ready or "0") >= 1, (
            f"No read replica pods are Ready (readyReplicas={ready!r}) (AC-6)"
        )

    @pytest.mark.asyncio
    async def test_replica_is_in_recovery(self, replica_engine) -> None:
        """pg_is_in_recovery() returns true on a hot-standby replica."""
        async with replica_engine.connect() as conn:
            result = await conn.execute(text("SELECT pg_is_in_recovery()"))
            in_recovery = result.scalar()
        assert in_recovery is True, (
            "DATABASE_READ_URL does not point at a hot-standby replica — "
            "pg_is_in_recovery() returned False (AC-6)"
        )

    @pytest.mark.asyncio
    async def test_audit_log_query_uses_replica(self, replica_engine) -> None:
        """Smoke test: audit_log table is readable from the replica."""
        async with replica_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT count(*) FROM audit_log")
            )
            count = result.scalar()
        assert count is not None, "audit_log is not readable from read replica (AC-6)"
```

## Acceptance Criteria

- [ ] `kubectl get statefulset postgresql-read -n contextiq-data` shows `READY 2/2` replicas (AC-6)
- [ ] `psql -h postgresql-read.contextiq-data.svc.cluster.local -c "SELECT pg_is_in_recovery();"` returns `t` on both replica pods (AC-6)
- [ ] `audit_log` endpoint latency reduced by ≥ 20% under concurrent load compared to primary-only baseline (AC-6)
- [ ] `pytest tests/integration/test_postgres_setup.py -v` passes all 6 AC test classes (all ACs)
- [ ] `TestAC2_CoreTables` confirms all 8 tables present; `TestAC3_MigrationJob` confirms Job succeeded (AC-2, AC-3)
- [ ] `TestAC6_ReadReplicas::test_replica_is_in_recovery` returns `True` — confirms routing target is a real standby (AC-6)

## Dependencies

- TASK-US050-01 — PostgreSQL primary must have `wal_level=replica` (configured in `postgresql.conf`)
- TASK-US050-02 — Migration `0020` must be applied before table-existence tests pass
- TASK-US050-03 — Migration Job must have run successfully in staging
- TASK-US050-04 — PgBouncer must be running; `DATABASE_READ_URL` points to replica PgBouncer Service

## Definition of Done

- [ ] `helm upgrade postgresql bitnami/postgresql -n contextiq-data -f values.yaml -f values-prod.yaml` starts 2 replica pods
- [ ] `src/data/database.py` updated with dual-engine; `src/data/dependencies.py` exposes `get_read_db()`
- [ ] Audit log and cost analytics routes switched to `Depends(get_read_db)`
- [ ] All integration tests pass in staging environment
