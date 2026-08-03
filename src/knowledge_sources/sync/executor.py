"""SyncJobExecutor — retry orchestration for knowledge source sync — TASK-US026-02.

Handles up to 3 retry attempts with exponential backoff (AC-4), emits a
`knowledge.source.synced` Kafka event on success (AC-5), and records sync
duration and document count delta as Prometheus metrics (AC-7).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.connector_sdk.registry import ConnectorRegistry
from src.knowledge_sources.repositories.knowledge_source_repository import (
    KnowledgeSourceRepository,
)
from src.knowledge_sources.repositories.sync_job_repository import SyncJobRepository
from src.knowledge_sources.schemas.knowledge_source import SourceStatus
from src.knowledge_sources.sync.metrics import (
    sync_document_count_delta,
    sync_duration_seconds,
    sync_retries_total,
)

_log = logging.getLogger(__name__)


class SyncExecutorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYNC_EXECUTOR_", env_file=".env", extra="ignore"
    )

    max_retries: int = 3  # US-026 AC-4
    backoff_base_s: float = 2.0  # wait = backoff_base_s ^ attempt (2, 4, 8 s)
    kafka_topic: str = "knowledge.source.synced"


_SCOPE_CONFIG_FIELD: dict[str, str] = {
    "github": "repos",
    "jira": "projects",
    "confluence": "spaces",
    "grafana": "dashboard_uids",
}


class SyncJobExecutor:
    def __init__(
        self,
        session: AsyncSession,
        registry: ConnectorRegistry,
        settings: SyncExecutorSettings | None = None,
    ) -> None:
        self._session = session
        self._registry = registry
        self._settings = settings or SyncExecutorSettings()

    async def _build_connector_for_source(self, source: object):  # type: ignore[return]
        """Build and authenticate a per-source connector.

        Injects the source's ``credentials_vault_path``, ``scope``, and the
        executor's live DB session so ``connector.sync()`` can persist the
        last-sync-at cursor via ``ConnectorSyncStore``.  This avoids the
        shared, session-less type-registered connector that ``load()`` creates
        at startup (which has ``session=None`` and no repo scope).
        """
        from src.agents.retrieval.connector_loader import CONNECTOR_CLASS_MAP

        connector_type = source.connector_type  # type: ignore[attr-defined]
        mapping = CONNECTOR_CLASS_MAP.get(connector_type)
        if mapping is None:
            raise ValueError(f"No connector implementation for '{connector_type}'")

        connector_cls, config_cls = mapping

        config_kwargs: dict[str, object] = {}
        vault_path = getattr(source, "credentials_vault_path", None)
        if vault_path:
            config_kwargs["vault_path"] = vault_path

        scope_field = _SCOPE_CONFIG_FIELD.get(connector_type)
        scope = getattr(source, "scope", None)
        if scope_field and scope:
            config_kwargs[scope_field] = [scope]

        # GitHub (and potentially others) accepts an optional session= kwarg
        # for ConnectorSyncStore.  Other connectors may not; fall back gracefully.
        try:
            connector = connector_cls(config=config_cls(**config_kwargs), session=self._session)
        except TypeError:
            connector = connector_cls(config=config_cls(**config_kwargs))

        await connector.authenticate()
        return connector

    async def run(self, source_id: UUID, is_full_sync: bool = False) -> UUID:
        """Execute a sync job for source_id with retry logic.

        Returns the sync job ID (for on-demand callers to poll status).
        """
        return await self._run_internal(source_id=source_id, is_full_sync=is_full_sync)

    async def run_existing_job(
        self,
        *,
        source_id: UUID,
        job_id: UUID,
        is_full_sync: bool = False,
    ) -> UUID:
        """Execute a sync using an existing queued job record.

        Used by the on-demand API route, which creates the job row up front so
        it can return the job ID immediately to the caller.
        """
        return await self._run_internal(
            source_id=source_id,
            is_full_sync=is_full_sync,
            job_id=job_id,
        )

    async def _run_internal(
        self,
        *,
        source_id: UUID,
        is_full_sync: bool,
        job_id: UUID | None = None,
    ) -> UUID:
        """Shared sync execution path with optional pre-created job row."""
        from src.events.producer import close_kafka_producer

        source_repo = KnowledgeSourceRepository(self._session)
        job_repo = SyncJobRepository(self._session)
        settings = self._settings
        job = None
        source = None
        started_at = time.perf_counter()

        try:
            source = await source_repo.get_by_id(source_id)
            if source is None:
                raise ValueError(f"Knowledge source {source_id} not found")

            if job_id is not None:
                job = await job_repo.get(job_id)
                if job is None:
                    raise ValueError(f"Sync job {job_id} not found")

            connector = await self._build_connector_for_source(source)

            # Mark source as syncing
            source.status = SourceStatus.SYNCING
            await self._session.flush()

            if job is None:
                job = await job_repo.create(
                    source_id=source_id, attempt_number=1, is_full_sync=is_full_sync
                )
            await self._session.commit()

            last_exc: Exception | None = None
            t0 = time.perf_counter()
            # max_retries=3 → 1 initial + 3 retries = 4 total attempts
            for attempt in range(1, settings.max_retries + 2):
                if attempt > 1:
                    wait = settings.backoff_base_s ** (attempt - 1)  # 2, 4, 8 s
                    _log.warning(
                        "sync_retry",
                        extra={
                            "source_id": str(source_id),
                            "attempt": attempt,
                            "wait_s": wait,
                        },
                    )
                    sync_retries_total.labels(connector_type=source.connector_type).inc()
                    await asyncio.sleep(wait)

                t0 = time.perf_counter()
                try:
                    if attempt > 1:
                        job.attempt_number = attempt
                        await self._session.flush()

                    sync_result = await connector.sync()
                    duration = time.perf_counter() - t0

                    await job_repo.mark_succeeded(
                        job_id=job.id,
                        items_processed=sync_result.items_processed,
                        items_failed=sync_result.items_failed,
                        duration_s=duration,
                    )
                    source.status = SourceStatus.ACTIVE
                    source.last_sync_at = datetime.utcnow()
                    source.document_count += sync_result.items_processed
                    await self._session.commit()

                    # Metrics (AC-7)
                    sync_duration_seconds.labels(
                        connector_type=source.connector_type, status="succeeded"
                    ).observe(duration)
                    sync_document_count_delta.labels(
                        connector_type=source.connector_type
                    ).inc(sync_result.items_processed)

                    # Kafka success event (AC-5)
                    await self._emit_synced_event(source, job.id, sync_result.items_processed)
                    return job.id

                except Exception as exc:
                    last_exc = exc
                    duration = time.perf_counter() - t0
                    sync_duration_seconds.labels(
                        connector_type=source.connector_type, status="failed"
                    ).observe(duration)
                    _log.error(
                        "sync_attempt_failed",
                        extra={
                            "source_id": str(source_id),
                            "attempt": attempt,
                            "error": str(exc),
                        },
                    )

            # All attempts exhausted
            await job_repo.mark_failed(
                job_id=job.id,
                error_message=str(last_exc),
                duration_s=time.perf_counter() - t0,
            )
            source.status = SourceStatus.ERROR
            await self._session.commit()
            return job.id
        except Exception as exc:
            if job is not None:
                await job_repo.mark_failed(
                    job_id=job.id,
                    error_message=str(exc),
                    duration_s=time.perf_counter() - started_at,
                )
                if source is not None:
                    source.status = SourceStatus.ERROR
                await self._session.commit()
            raise
        finally:
            await close_kafka_producer()

    async def _emit_synced_event(
        self, source: object, job_id: UUID, items_processed: int
    ) -> None:
        from src.events.producer import get_kafka_producer

        event = {
            "event_type": "knowledge_source_synced",
            "source_id": str(source.id),  # type: ignore[attr-defined]
            # knowledge_sources has no tenant_id column yet (single-tenant
            # local dev); "default" matches the fallback used elsewhere
            # (e.g. src/governance/nodes/opa_filter_node.py). Required by
            # SourceSyncedEvent — omitting it made IndexingConsumer silently
            # drop every sync event with a pydantic ValidationError.
            "tenant_id": "default",
            "job_id": str(job_id),
            "connector_type": source.connector_type,  # type: ignore[attr-defined]
            "scope": source.scope,  # type: ignore[attr-defined]
            "items_processed": items_processed,
            "synced_at": datetime.now(tz=UTC).isoformat(),
        }
        producer = await get_kafka_producer()
        await producer.send_and_wait(
            self._settings.kafka_topic,
            value=json.dumps(event).encode(),
        )
