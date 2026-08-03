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
import logging
import re
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

logger = logging.getLogger(__name__)

_FALLBACK_QUERY_STOPWORDS: set[str] = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your",
    "only", "full", "before", "after", "about", "include", "available",
    "explicitly", "summary", "answer", "return", "working", "local",
    "still", "empty", "context", "package", "json", "evidence",
    "github", "contextiq", "repo", "retrieved", "returns",
    "any", "base", "concrete", "explain", "fix", "items", "now",
    "raw", "say", "why",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


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
        credential = await self._token_provider.get_credential()
        self._credential = credential

        health = await self.health_check()
        if not health.healthy:
            self._credential = None
            raise ConnectorAuthError(f"GitHub credential validation failed: {health.message}")

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

        Enforces a configured total latency budget via ``asyncio.wait_for()``.

        Raises:
            ConnectorAuthError: when ``authenticate()`` has not been called.
            asyncio.TimeoutError: when total search and enrichment exceeds the
                configured fetch timeout.
        """
        return await asyncio.wait_for(
            self._fetch_inner(query),
            timeout=self._config.fetch_timeout_s,
        )

    async def _fetch_inner(self, query: ConnectorQuery) -> list[ConnectorResult]:
        search_client = GitHubSearchClient(self._config)
        content_client = GitHubContentClient(self._config)
        auth = self._auth_header()
        branch = query.filters.get("branch", "main")

        try:
            items = await search_client.search_code(
                query=query.query,
                repos=self._config.repos,
                auth_header=auth,
                max_results=query.max_results,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response is None or exc.response.status_code not in {403, 422}:
                raise
            items = []

        if not items:
            return await self._fallback_fetch_from_repo_paths(
                query=query.query,
                branch=branch,
                content_client=content_client,
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
                    branch=branch,
                )
                for item in items
            ]
            enriched = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[ConnectorResult] = []
        for item, enrichment in zip(items, enriched, strict=False):
            if isinstance(enrichment, Exception):
                continue  # skip files that could not be enriched; do not fail the batch
            excerpt, commit_sha, committed_at = enrichment

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

    async def _fallback_fetch_from_repo_paths(
        self,
        *,
        query: str,
        branch: str,
        content_client: GitHubContentClient,
        auth_header: dict[str, str],
        max_results: int,
    ) -> list[ConnectorResult]:
        keywords = _extract_fallback_keywords(query)
        max_files = max(50, min(max_results * 50, 200))

        candidates: list[tuple[int, str, str]] = []
        selected_branch_by_repo: dict[str, str] = {}
        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            for repo in self._config.repos:
                try:
                    selected_branch, paths = await content_client.list_repo_files_with_branch(
                        client=client,
                        repo=repo,
                        auth_header=auth_header,
                        branch=branch,
                        max_files=max_files,
                    )
                except Exception:
                    continue

                selected_branch_by_repo[repo] = selected_branch or branch

                for path in paths:
                    score = _score_fallback_path(path, keywords)
                    candidates.append((score, repo, path))

            if not candidates:
                return []

            candidates.sort(key=lambda item: (-item[0], item[2]))
            selected = candidates[: max(max_results, 1)]

            tasks = [
                content_client.fetch_content_and_commit(
                    client=client,
                    repo=repo,
                    file_path=path,
                    auth_header=auth_header,
                    branch=selected_branch_by_repo.get(repo, branch),
                )
                for _score, repo, path in selected
            ]
            enriched = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[ConnectorResult] = []
        for (_score, repo, path), enrichment in zip(selected, enriched, strict=False):
            if isinstance(enrichment, Exception):
                continue
            excerpt, commit_sha, committed_at = enrichment
            if not excerpt.strip():
                continue
            results.append(
                ConnectorResult(
                    source_id=f"github:{repo}:{path}",
                    content=excerpt,
                    metadata=ResultMetadata(
                        source_url=(
                            f"https://github.com/{repo}/blob/"
                            f"{selected_branch_by_repo.get(repo, branch)}/{path}"
                        ),
                        author=None,
                        last_modified=committed_at,
                        extra={
                            "file_path": path,
                            "repository": repo,
                            "branch": selected_branch_by_repo.get(repo, branch),
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
                    selected_branch, paths = await content_client.list_repo_files_with_branch(
                        client=client,
                        repo=repo,
                        auth_header=auth,
                        max_files=max_files_per_repo,
                    )
                except Exception:
                    continue  # skip repos we can't list; do not fail the whole batch

                tasks = [
                    content_client.fetch_content_and_commit(
                        client=client,
                        repo=repo,
                        file_path=path,
                        auth_header=auth,
                        branch=selected_branch or "main",
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
                            # Use a file-stable document id so indexed document
                            # counts reflect unique repo files instead of
                            # collapsing every file touched by the same commit.
                            document_id=f"github:{repo}:{path}",
                            text=excerpt,
                            token_count=max(1, len(excerpt) // 4),
                            metadata={
                                "repository": repo,
                                "file_path": path,
                                "commit_sha": sha,
                            },
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
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
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


def _extract_fallback_keywords(query: str) -> set[str]:
    keywords: set[str] = set()
    for token in _tokenize_overlap_text(query):
        if len(token) < 3 or token in _FALLBACK_QUERY_STOPWORDS:
            continue
        keywords.add(token)
    return keywords


def _score_fallback_path(path: str, keywords: set[str]) -> int:
    lowered = path.lower()
    path_tokens = _tokenize_overlap_text(lowered)
    overlap = len(path_tokens & keywords)

    score = overlap * 5
    if lowered.startswith("src/"):
        score += 7
    elif "/src/" in lowered:
        score += 2
    if lowered.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".kt", ".rb", ".cs")):
        score += 3
    if lowered.startswith(("src/agents/", "src/gateway/", "src/knowledge_sources/", "src/retrieval/")):
        score += 8
    if "/__tests__/" in lowered or ".test." in lowered or ".spec." in lowered:
        score -= 10
    if lowered.startswith("frontend/"):
        score -= 3
    if any(part in lowered for part in ("/node_modules/", "/dist/", "/build/", "/vendor/", "/coverage/", "/.venv/")):
        score -= 12
    if lowered.startswith(".github/") or "/.github/" in lowered:
        score -= 8
    if lowered.startswith(".npm-package/") or lowered.startswith(".propel/"):
        score -= 8
    if lowered.startswith("docs/") or lowered.endswith(".md"):
        score -= 3
    return score


def _tokenize_overlap_text(text: str) -> set[str]:
    normalized = re.sub(r"[\/_.-]+", " ", text.lower())
    tokens = set(_WORD_RE.findall(normalized))
    singularized = {
        token[:-1]
        for token in tokens
        if token.endswith("s") and len(token) > 4
    }
    return tokens | singularized
