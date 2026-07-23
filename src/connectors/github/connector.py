"""
GitHubConnector — BaseConnector implementation for GitHub.

TASK-US022-01: GitHubConnectorConfig, Vault Token Provider, and authenticate().
TASK-US022-03: fetch() — translates ConnectorQuery to GitHub Code Search results.

This module contains the connector with ``authenticate()`` wired to
``GitHubTokenProvider`` and ``fetch()`` wired to ``GitHubSearchClient`` /
``GitHubContentClient``.  The ``sync()`` and ``health_check()`` methods are
stubbed and will be implemented in subsequent tasks.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.connector_sdk.base import BaseConnector
from src.connector_sdk.exceptions import ConnectorAuthError
from src.connector_sdk.schemas.health import HealthStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult, ResultMetadata
from src.connector_sdk.schemas.sync import SyncResult
from src.connectors.github.auth import GitHubCredential, GitHubTokenProvider
from src.connectors.github.config import GitHubConnectorConfig
from src.connectors.github.content_client import GitHubContentClient
from src.connectors.github.search_client import GitHubSearchClient
from src.connectors.github.sync_client import GitHubCommitsClient
from src.connectors.github.sync_store import ConnectorSyncStore
from src.events.producer import get_kafka_producer
from src.indexing.schemas.chunk import ChunkPayload


class GitHubConnector(BaseConnector):
    """
    Connector for GitHub repositories.

    Call ``authenticate()`` before any other method.  Credentials are cached
    in memory and never written to logs, state, or PostgreSQL.
    """

    def __init__(
        self,
        config: GitHubConnectorConfig | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        self._config = config or GitHubConnectorConfig()
        self._session = session          # injected for sync; None in fetch-only usage
        self._token_provider = GitHubTokenProvider(self._config)
        self._credential: GitHubCredential | None = None  # set by authenticate()

    async def authenticate(self) -> None:
        """
        Acquire a GitHub token from Vault and cache it for subsequent API calls.

        Re-called by ConnectorHealthPoller on auth expiry.

        Raises:
            ConnectorAuthError: when the Vault request fails or the secret is
                missing the required ``"token"`` key.
        """
        self._credential = await self._token_provider.get_credential()

    def _auth_header(self) -> dict[str, str]:
        """
        Return the ``Authorization`` header for GitHub API requests.

        Raises:
            ConnectorAuthError: when ``authenticate()`` has not yet been called.
        """
        if self._credential is None:
            raise ConnectorAuthError("authenticate() has not been called")
        return {"Authorization": f"Bearer {self._credential.token}"}

    # ------------------------------------------------------------------
    # fetch — TASK-US022-03
    # ------------------------------------------------------------------

    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        """
        Search GitHub code and enrich each result with content excerpt and
        commit metadata.

        Enforces a 2-second total latency budget via ``asyncio.wait_for()``.

        Raises:
            ConnectorAuthError: when ``authenticate()`` has not been called.
            asyncio.TimeoutError: when total enrichment exceeds 2 seconds.
        """
        return await asyncio.wait_for(
            self._fetch_inner(query),
            timeout=2.0,  # US-022 AC-7
        )

    async def _fetch_inner(self, query: ConnectorQuery) -> list[ConnectorResult]:
        search_client = GitHubSearchClient(self._config)
        content_client = GitHubContentClient(self._config)
        auth = self._auth_header()

        items = await search_client.search_code(
            query=query.query,
            repos=self._config.repos,
            auth_header=auth,
            max_results=query.max_results,
        )

        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            tasks = [
                content_client.fetch_content_and_commit(
                    client=client,
                    repo=item.repository,
                    file_path=item.path,
                    auth_header=auth,
                )
                for item in items
            ]
            enriched = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[ConnectorResult] = []
        for item, enrichment in zip(items, enriched, strict=False):
            if isinstance(enrichment, Exception):
                continue  # skip files that could not be enriched; do not fail the batch
            excerpt, commit_sha, committed_at = enrichment

            # Derive branch from filters; default to "main" if not specified
            branch = query.filters.get("branch", "main")

            results.append(
                ConnectorResult(
                    source_id=f"github:{item.repository}:{item.sha}",
                    content=excerpt,
                    metadata=ResultMetadata(
                        source_url=item.html_url,
                        author=None,  # EP-008 can enrich with blame data
                        last_modified=committed_at,
                        extra={
                            "file_path": item.path,
                            "repository": item.repository,
                            "branch": branch,
                            "commit_sha": commit_sha,
                        },
                    ),
                    fetched_at=datetime.now(tz=UTC),
                )
            )

        return results

    async def sync(self) -> SyncResult:
        """
        Incremental sync: fetch files changed since last_sync_at.

        Falls back to ``now - default_days`` when no prior sync record exists.
        Emits a DR-005 StateTransitionEvent to ``contextiq.source.sync`` on
        completion.

        Raises:
            ConnectorAuthError: when ``authenticate()`` has not been called.
        """
        if self._credential is None:
            raise ConnectorAuthError("authenticate() has not been called")

        sync_store = ConnectorSyncStore(self._session) if self._session is not None else None
        commits_client = GitHubCommitsClient(self._config)
        auth = self._auth_header()
        now = datetime.now(tz=UTC)

        last_sync: datetime | None = None
        if sync_store is not None:
            try:
                last_sync = await sync_store.get_last_sync_at("github")
            except Exception:
                last_sync = None  # table may not exist yet; fall back to default lookback

        if last_sync is None:
            from datetime import timedelta

            last_sync = now - timedelta(days=self._config.default_days)

        items_processed = 0
        items_failed = 0
        errors: list[str] = []

        for repo in self._config.repos:
            try:
                changed_paths = await commits_client.fetch_changed_files(
                    repo=repo,
                    since=last_sync,
                    auth_header=auth,
                )
                items_processed += len(changed_paths)
            except Exception as exc:
                items_failed += 1
                errors.append(f"{repo}: {type(exc).__name__}: {exc}")

        if sync_store is not None:
            try:
                await sync_store.set_last_sync_at("github", now)
            except Exception:
                pass  # best-effort; failure here does not invalidate the sync result
        await self._emit_sync_event(items_processed=items_processed, synced_at=now)

        return SyncResult(
            items_processed=items_processed,
            items_failed=items_failed,
            last_sync_at=now,
            errors=errors,
        )

    async def _emit_sync_event(self, items_processed: int, synced_at: datetime) -> None:
        """Emit DR-005 StateTransitionEvent to ``contextiq.source.sync`` Kafka topic."""
        import json

        event = {
            "event_type": "source_sync_completed",
            "connector_id": "github",
            "items_processed": items_processed,
            "synced_at": synced_at.isoformat(),
        }
        producer = await get_kafka_producer()
        await producer.send_and_wait(
            "contextiq.source.sync",
            value=json.dumps(event).encode(),
        )

    async def get_chunks(
        self,
        source_id: UUID,
        tenant_id: str,
        max_files_per_repo: int = 50,
    ) -> list[ChunkPayload]:
        """
        Fetch a full text snapshot of this connector's configured repos for
        the EP-008 indexing pipeline.

        Unlike ``fetch()`` (GitHub Code Search — requires search keywords and
        cannot enumerate "everything"), this uses the Git Trees API via
        ``GitHubContentClient.list_repo_files()`` to list indexable files,
        then fetches each file's content. One ``ChunkPayload`` is produced per
        file (no further splitting yet — large files are naturally capped at
        2000 chars by ``fetch_content_and_commit``'s excerpt truncation).

        Repos/files that fail to list or fetch are skipped so one bad repo
        does not fail the whole batch.

        Raises:
            ConnectorAuthError: when ``authenticate()`` has not been called.
        """
        if self._credential is None:
            raise ConnectorAuthError("authenticate() has not been called")

        auth = self._auth_header()
        content_client = GitHubContentClient(self._config)
        chunks: list[ChunkPayload] = []

        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            for repo in self._config.repos:
                try:
                    paths = await content_client.list_repo_files(
                        client=client,
                        repo=repo,
                        auth_header=auth,
                        max_files=max_files_per_repo,
                    )
                except Exception:
                    continue  # skip repos we can't list; do not fail the whole batch

                tasks = [
                    content_client.fetch_content_and_commit(
                        client=client, repo=repo, file_path=path, auth_header=auth
                    )
                    for path in paths
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for path, result in zip(paths, results, strict=False):
                    if isinstance(result, BaseException):
                        continue  # skip files that could not be fetched
                    excerpt, sha, _committed_at = result
                    if not excerpt.strip():
                        continue  # skip empty files
                    chunks.append(
                        ChunkPayload(
                            source_id=source_id,
                            tenant_id=tenant_id,
                            document_id=f"github:{repo}:{sha}",
                            text=excerpt,
                            token_count=max(1, len(excerpt) // 4),
                            metadata={"repository": repo, "file_path": path},
                        )
                    )

        return chunks

    async def health_check(self) -> HealthStatus:
        """
        Validate the cached token by calling GET /rate_limit.
        Must not raise — all exceptions are caught and reported as unhealthy.
        """
        now = datetime.now(tz=UTC)
        try:
            if self._credential is None:
                return HealthStatus(
                    healthy=False,
                    message="Not authenticated; call authenticate() first",
                    checked_at=now,
                )
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._config.base_url}/rate_limit",
                    headers={
                        **self._auth_header(),
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
            if resp.status_code == 200:
                remaining = resp.json().get("rate", {}).get("remaining", -1)
                return HealthStatus(
                    healthy=True,
                    message=f"GitHub API reachable; rate_limit.remaining={remaining}",
                    checked_at=now,
                )
            return HealthStatus(
                healthy=False,
                message=f"GitHub /rate_limit returned HTTP {resp.status_code}",
                checked_at=now,
            )
        except Exception as exc:
            return HealthStatus(
                healthy=False,
                message=f"{type(exc).__name__}: {str(exc)[:150]}",
                checked_at=now,
            )
