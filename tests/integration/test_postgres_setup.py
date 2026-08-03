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
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL      = os.environ.get("DATABASE_URL", "postgresql+asyncpg://localhost/contextiq")
DATABASE_READ_URL = os.environ.get("DATABASE_READ_URL", DATABASE_URL)


@pytest.fixture(scope="session")
def primary_engine():
    engine = create_async_engine(
        DATABASE_URL,
        connect_args={"statement_cache_size": 0, "ssl": "require"},
    )
    yield engine
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(engine.dispose())
    finally:
        loop.close()


@pytest.fixture(scope="session")
def replica_engine():
    engine = create_async_engine(
        DATABASE_READ_URL,
        connect_args={"statement_cache_size": 0, "ssl": "require"},
    )
    yield engine
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(engine.dispose())
    finally:
        loop.close()


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
            "PVC does not use contextiq-encrypted-gp3 StorageClass (AC-1)"
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
            ["python", "-m", "alembic", "current"],
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
        """run_migration.py with an invalid URL must exit 1 and emit migration_error JSON."""
        result = subprocess.run(
            ["python", "-m", "scripts.ci.run_migration"],
            capture_output=True, timeout=30,
            env={**os.environ, "DATABASE_URL": "postgresql+asyncpg://bad:bad@localhost:9999/nodb"},
        )
        assert result.returncode == 1, (
            "run_migration.py did not exit 1 on a bad DATABASE_URL (AC-4)"
        )
        # run_migration.py emits structured JSON to stdout only (Loki forwarding)
        assert b"migration_error" in result.stdout, (
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
    async def test_pgbouncer_connectivity(self, primary_engine) -> None:
        """Smoke test: application can connect through PgBouncer."""
        async with primary_engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1, "Basic SELECT 1 failed through PgBouncer (AC-5)"


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
        """pg_is_in_recovery() returns True on a hot-standby replica."""
        async with replica_engine.connect() as conn:
            result = await conn.execute(text("SELECT pg_is_in_recovery()"))
            in_recovery = result.scalar()
        assert in_recovery is True, (
            "DATABASE_READ_URL does not point at a hot-standby replica — "
            "pg_is_in_recovery() returned False (AC-6)"
        )

    @pytest.mark.asyncio
    async def test_audit_log_readable_from_replica(self, replica_engine) -> None:
        """Smoke test: audit_log table is readable from the read replica."""
        async with replica_engine.connect() as conn:
            result = await conn.execute(text("SELECT count(*) FROM audit_log"))
            count = result.scalar()
        assert count is not None, "audit_log is not readable from read replica (AC-6)"
