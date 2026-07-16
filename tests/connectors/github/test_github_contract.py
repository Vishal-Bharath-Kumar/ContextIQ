"""
Contract tests for GitHubConnector against BaseConnectorTestCase.

TASK-US022-05: GitHubConnector.health_check() and Contract Test Suite.

All HTTP calls are mocked via respx; no live GitHub API calls in CI.
"""
from __future__ import annotations

import asyncio
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.sync import SyncResult
from src.connector_sdk.testing import BaseConnectorTestCase
from src.connectors.github.config import GitHubConnectorConfig
from src.connectors.github.connector import GitHubConnector

_BASE_URL = "https://api.github.com"
_TOKEN = "ghp_testtoken"
_REPO = "acme/backend"

MOCK_CONFIG = GitHubConnectorConfig.model_validate(
    {
        "repos": [_REPO],
        "vault_path": "secret/data/github/token",
        "vault_role_id": "test-role",
        "vault_secret_id": "test-secret",
        "base_url": _BASE_URL,
    }
)


@pytest.fixture
def mock_vault_credential() -> Generator[None, None, None]:
    """Patch GitHubTokenProvider.get_credential to return a fixture credential."""
    from src.connectors.github.auth import GitHubCredential

    with patch(
        "src.connectors.github.connector.GitHubTokenProvider.get_credential",
        new_callable=AsyncMock,
        return_value=GitHubCredential(token=_TOKEN, token_type="pat"),
    ):
        yield


def _make_search_item(n: int, repo: str = _REPO) -> dict:
    return {
        "name": f"file{n}.py",
        "path": f"src/file{n}.py",
        "repository": repo,
        "html_url": f"https://github.com/{repo}/blob/main/src/file{n}.py",
        "sha": f"sha{n:04d}",
        "url": f"{_BASE_URL}/repos/{repo}/git/blobs/sha{n:04d}",
    }


def _mock_sync_dependencies(connector: GitHubConnector) -> None:
    """Patch sync() I/O dependencies (DB, Kafka) on the connector instance."""
    mock_store = MagicMock()
    mock_store.get_last_sync_at = AsyncMock(return_value=None)
    mock_store.set_last_sync_at = AsyncMock(return_value=None)

    mock_commits = MagicMock()
    mock_commits.fetch_changed_files = AsyncMock(return_value=["src/file1.py"])

    connector._mock_store = mock_store
    connector._mock_commits = mock_commits


class TestGitHubConnector(BaseConnectorTestCase):
    """BaseConnectorTestCase contract suite wired to GitHubConnector."""

    @pytest.fixture
    def make_connector(self, mock_vault_credential: None) -> GitHubConnector:  # noqa: ARG002
        return GitHubConnector(config=MOCK_CONFIG)

    @pytest.fixture
    def sample_query(self) -> ConnectorQuery:
        return ConnectorQuery(query="def authenticate", max_results=5)

    # ------------------------------------------------------------------
    # Override: fetch — provide respx HTTP mocks
    # ------------------------------------------------------------------

    @respx.mock
    async def test_fetch_returns_list_of_connector_results(
        self,
        make_connector: GitHubConnector,
        sample_query: ConnectorQuery,
        mock_vault_credential: None,
    ) -> None:
        await make_connector.authenticate()

        respx.get(f"{_BASE_URL}/search/code").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "name": "connector.py",
                            "path": "src/connector.py",
                            "repository": _REPO,
                            "html_url": f"https://github.com/{_REPO}/blob/main/src/connector.py",
                            "sha": "abc123",
                            "url": f"{_BASE_URL}/repos/{_REPO}/contents/src/connector.py",
                        }
                    ]
                },
            )
        )
        respx.get(f"{_BASE_URL}/repos/{_REPO}/contents/src/connector.py").mock(
            return_value=httpx.Response(200, text="def authenticate(): pass")
        )
        respx.get(f"{_BASE_URL}/repos/{_REPO}/commits").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "sha": "abc123",
                        "commit": {"committer": {"date": "2026-07-01T10:00:00Z"}},
                    }
                ],
            )
        )

        results = await make_connector.fetch(sample_query)
        assert results
        assert results[0].metadata.extra["repository"] == _REPO
        assert results[0].metadata.extra["commit_sha"] == "abc123"

    @respx.mock
    async def test_fetch_respects_max_results(
        self, make_connector: GitHubConnector, sample_query: ConnectorQuery
    ) -> None:
        """fetch() must return at most max_results items (5 in sample_query)."""
        await make_connector.authenticate()

        respx.get(f"{_BASE_URL}/search/code").mock(
            return_value=httpx.Response(
                200,
                json={"items": [_make_search_item(i) for i in range(1, 4)]},
            )
        )
        for i in range(1, 4):
            respx.get(f"{_BASE_URL}/repos/{_REPO}/contents/src/file{i}.py").mock(
                return_value=httpx.Response(200, text=f"# file {i}")
            )
        respx.get(f"{_BASE_URL}/repos/{_REPO}/commits").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "sha": "commitabc",
                        "commit": {"committer": {"date": "2026-07-01T10:00:00Z"}},
                    }
                ],
            )
        )

        results = await make_connector.fetch(sample_query)
        assert len(results) <= sample_query.max_results

    # ------------------------------------------------------------------
    # Override: sync — patch I/O-heavy dependencies
    # ------------------------------------------------------------------

    async def test_sync_returns_sync_result(self, make_connector: GitHubConnector) -> None:
        await make_connector.authenticate()

        mock_store = MagicMock()
        mock_store.get_last_sync_at = AsyncMock(return_value=None)
        mock_store.set_last_sync_at = AsyncMock(return_value=None)

        mock_producer = MagicMock()
        mock_producer.send_and_wait = AsyncMock(return_value=None)

        with (
            patch(
                "src.connectors.github.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.github.connector.GitHubCommitsClient.fetch_changed_files",
                new_callable=AsyncMock,
                return_value=["src/file1.py"],
            ),
            patch(
                "src.connectors.github.connector.get_kafka_producer",
                new_callable=AsyncMock,
                return_value=mock_producer,
            ),
        ):
            result = await make_connector.sync()

        assert isinstance(result, SyncResult)
        assert result.items_processed >= 0
        assert result.items_failed >= 0

    # ------------------------------------------------------------------
    # health_check — inherits from BaseConnectorTestCase:
    #   test_health_check_returns_health_status
    #   test_health_check_does_not_raise_on_repeated_calls
    # Both pass without HTTP mocks: health_check returns unhealthy when
    # called before authenticate() (no live HTTP call is made).
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Performance — 2-second SLA for ≤ 50 results
    # ------------------------------------------------------------------

    @pytest.mark.benchmark
    @respx.mock
    def test_fetch_under_2_seconds(self, benchmark: object, mock_vault_credential: None) -> None:
        """fetch() mean latency must be < 2 s for ≤ 50 mocked results."""
        n = 10  # use 10 items — each needs 2 HTTP round-trips (content + commits)

        respx.get(f"{_BASE_URL}/search/code").mock(
            return_value=httpx.Response(
                200,
                json={"items": [_make_search_item(i) for i in range(1, n + 1)]},
            )
        )
        for i in range(1, n + 1):
            respx.get(f"{_BASE_URL}/repos/{_REPO}/contents/src/file{i}.py").mock(
                return_value=httpx.Response(200, text=f"# content {i}")
            )
        respx.get(f"{_BASE_URL}/repos/{_REPO}/commits").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "sha": "perf_commit",
                        "commit": {"committer": {"date": "2026-07-01T10:00:00Z"}},
                    }
                ],
            )
        )

        connector = GitHubConnector(config=MOCK_CONFIG)

        async def run() -> list:
            await connector.authenticate()
            return await connector.fetch(ConnectorQuery(query="def", max_results=n))

        benchmark(lambda: asyncio.run(run()))
        assert benchmark.stats["mean"] < 2.0, (
            f"fetch() mean latency {benchmark.stats['mean']:.2f}s exceeded 2 s SLA"
        )
