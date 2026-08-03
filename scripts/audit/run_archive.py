"""
Daily audit log archival — Kubernetes CronJob entrypoint.

Invoked at 02:00 UTC by the `audit-log-archiver` CronJob.
Exits with code 0 on success, non-zero on failure so that the CronJob
controller marks the run as Failed and triggers PagerDuty alerting.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from src.audit.admin_audit_log.archive_service import AuditArchiveService
from src.audit.admin_audit_log.archive_settings import ArchiveSettings

# BUG FIX (spec): `from src.db.session import get_async_session_context` does
# not exist.  The database module is `src.data.database`; standalone scripts
# create a session directly from `primary_session_factory` rather than using
# FastAPI's `get_db` dependency (which requires a request context).
from src.data.database import primary_session_factory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def _run() -> None:
    settings = ArchiveSettings()
    service = AuditArchiveService(settings)

    async with primary_session_factory()() as session:
        count = await service.archive_day(session)
        await session.commit()

    logger.info("audit_archive: complete — %d rows archived", count)


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("audit_archive: FAILED — %s", exc, exc_info=True)
        sys.exit(1)
