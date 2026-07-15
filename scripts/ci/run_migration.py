"""
Alembic migration runner with structured JSON logging.
Invoked by the Kubernetes pre-sync Job:
    python -m scripts.ci.run_migration

AC-3: exits 0 on success; exits 1 on any failure — ArgoCD hook respects the exit code.
AC-4: all output is structured JSON so Loki can index fields for alerting.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text


def _log(event: str, **kwargs: object) -> None:
    """Emit a structured JSON log line to stdout (Loki/Promtail collects container stdout)."""
    record: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event":     event,
        **kwargs,
    }
    print(json.dumps(record), flush=True)


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        _log("migration_error", error="DATABASE_URL environment variable is not set")
        return 1

    # Alembic + synchronous SQLAlchemy require a non-asyncpg URL for DDL operations
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    # Mask credentials in log output — only log the host/db portion
    masked = sync_url.split("@")[-1] if "@" in sync_url else "unknown"
    _log("migration_connecting", target=masked)

    try:
        engine = create_engine(sync_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _log("migration_db_connected")
    except Exception as exc:
        _log("migration_error", error=str(exc), phase="db_connect")
        return 1

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)

    # Record current revision before migration for rollback visibility
    current_rev: str | None = None
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_rev = ctx.get_current_revision()
        _log("migration_current_revision", revision=current_rev)
    except Exception as exc:
        _log("migration_warning", warning=f"Could not read current revision: {exc}")

    start = time.monotonic()
    try:
        command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        _log(
            "migration_failed",
            error=str(exc),
            current_revision=current_rev,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return 1

    elapsed_ms = int((time.monotonic() - start) * 1000)

    new_rev: str | None = None
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            new_rev = ctx.get_current_revision()
    except Exception as exc:
        _log("migration_warning", warning=f"Could not read new revision after upgrade: {exc}")

    _log(
        "migration_succeeded",
        previous_revision=current_rev,
        current_revision=new_rev,
        duration_ms=elapsed_ms,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
