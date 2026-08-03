"""
Unit tests for TASK-US022-03: GitHubConnector.fetch() — Results Mapping to ConnectorResult.

All HTTP calls are mocked via respx; no live GitHub API calls in CI.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from src.connector_sdk.exceptions import ConnectorAuthError
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult
from src.connectors.github.config import GitHubConnectorConfig
from src.connectors.github.connector import GitHubConnector
from src.connectors.github.content_client import GitHubContentClient

_BASE_URL = "https://api.github.com"
_SEARCH_URL = f"{_BASE_URL}/search/code"
_TOKEN = "ghp_test_token"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> GitHubConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": _BASE_URL,
        "fetch_timeout_s": 8.0,
        "request_timeout_s": 10.0,
        "repos": ["owner/repo"],
    }
    defaults.update(overrides)
    return GitHubConnectorConfig.model_validate(defaults)


def _make_search_item(n: int = 1) -> dict:
    return {
        "name": f"file{n}.py",
        "path": f"src/file{n}.py",
        "repository": "owner/repo",
        "html_url": f"https://github.com/owner/repo/blob/main/src/file{n}.py",
        "sha": f"blobsha{n:04d}",
        "url": f"{_BASE_URL}/repos/owner/repo/git/blobs/blobsha{n:04d}",
    }


def _content_url(path: str) -> str:
    return f"{_BASE_URL}/repos/owner/repo/contents/{path}"


def _trees_url(repo: str = "owner/repo", branch: str = "main") -> str:
    return f"{_BASE_URL}/repos/{repo}/git/trees/{branch}"


def _commits_url() -> str:
    return f"{_BASE_URL}/repos/owner/repo/commits"


def _make_commit_response(sha: str = "commitabc123", date: str = "2024-01-15T10:00:00Z") -> list:
    return [
        {
            "sha": sha,
            "commit": {
                "committer": {"date": date},
            },
        }
    ]


def _tree_response(paths: list[tuple[str, str]]) -> dict:
    return {"tree": [{"path": p, "type": t} for p, t in paths]}


async def _authenticated_connector(config: GitHubConnectorConfig | None = None) -> GitHubConnector:
    """Return a connector with authenticate() already called (token mocked)."""
    connector = GitHubConnector(config or _make_config())
    with patch.object(
        connector._token_provider,
        "get_credential",
        new=AsyncMock(
            return_value=type("Cred", (), {"token": _TOKEN})()
        ),
    ), patch.object(
        connector,
        "health_check",
        new=AsyncMock(return_value=type("Health", (), {"healthy": True, "message": "ok"})()),
    ):
        await connector.authenticate()
    return connector


# ---------------------------------------------------------------------------
# AC: source_id pattern github:{repo}:{sha}
# ---------------------------------------------------------------------------


class TestFetchSourceId:
    @respx.mock
    async def test_source_id_matches_pattern(self) -> None:
        """source_id must follow 'github:{repo}:{blob_sha}' pattern."""
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": [_make_search_item(1)]})
        )
        respx.get(_content_url("src/file1.py")).mock(
            return_value=httpx.Response(200, text="print('hello')")
        )
        respx.get(_commits_url()).mock(
            return_value=httpx.Response(200, json=_make_commit_response())
        )

        connector = await _authenticated_connector()
        results = await connector.fetch(ConnectorQuery(query="hello"))

        assert len(results) == 1
        assert results[0].source_id == "github:owner/repo:blobsha0001"

    @respx.mock
    async def test_source_id_uses_blob_sha_not_commit_sha(self) -> None:
        """source_id uses the blob SHA from search results, not the commit SHA."""
        item = _make_search_item(7)
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": [item]})
        )
        respx.get(_content_url("src/file7.py")).mock(
            return_value=httpx.Response(200, text="content")
        )
        respx.get(_commits_url()).mock(
            return_value=httpx.Response(200, json=_make_commit_response("different_commit_sha"))
        )

        connector = await _authenticated_connector()
        results = await connector.fetch(ConnectorQuery(query="content"))

        assert results[0].source_id == "github:owner/repo:blobsha0007"


# ---------------------------------------------------------------------------
# AC: metadata.extra fields
# ---------------------------------------------------------------------------


class TestFetchMetadataExtra:
    @respx.mock
    async def test_extra_contains_required_fields(self) -> None:
        """metadata.extra must contain file_path, repository, branch, commit_sha."""
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": [_make_search_item(1)]})
        )
        respx.get(_content_url("src/file1.py")).mock(
            return_value=httpx.Response(200, text="code")
        )
        respx.get(_commits_url()).mock(
            return_value=httpx.Response(200, json=_make_commit_response("sha123"))
        )

        connector = await _authenticated_connector()
        results = await connector.fetch(ConnectorQuery(query="code"))

        extra = results[0].metadata.extra
        assert extra["file_path"] == "src/file1.py"
        assert extra["repository"] == "owner/repo"
        assert extra["branch"] == "main"
        assert extra["commit_sha"] == "sha123"

    @respx.mock
    async def test_branch_from_filter(self) -> None:
        """branch in metadata.extra is taken from query.filters['branch'] if provided."""
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": [_make_search_item(1)]})
        )
        respx.get(_content_url("src/file1.py")).mock(
            return_value=httpx.Response(200, text="code")
        )
        respx.get(_commits_url()).mock(
            return_value=httpx.Response(200, json=_make_commit_response())
        )

        connector = await _authenticated_connector()
        results = await connector.fetch(
            ConnectorQuery(query="code", filters={"branch": "develop"})
        )

        assert results[0].metadata.extra["branch"] == "develop"

    @respx.mock
    async def test_branch_defaults_to_main(self) -> None:
        """branch defaults to 'main' when not in query.filters."""
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": [_make_search_item(1)]})
        )
        respx.get(_content_url("src/file1.py")).mock(
            return_value=httpx.Response(200, text="code")
        )
        respx.get(_commits_url()).mock(
            return_value=httpx.Response(200, json=_make_commit_response())
        )

        connector = await _authenticated_connector()
        results = await connector.fetch(ConnectorQuery(query="code"))

        assert results[0].metadata.extra["branch"] == "main"


# ---------------------------------------------------------------------------
# AC: timeout raises asyncio.TimeoutError
# ---------------------------------------------------------------------------


class TestFetchTimeout:
    async def test_raises_timeout_error_on_slow_fetch(self) -> None:
        """fetch() must raise asyncio.TimeoutError when enrichment exceeds the configured budget."""

        async def _slow_inner(_query: ConnectorQuery) -> list[ConnectorResult]:
            await asyncio.sleep(10)
            return []

        connector = await _authenticated_connector(_make_config(fetch_timeout_s=0.01))
        with patch.object(connector, "_fetch_inner", side_effect=_slow_inner):
            with pytest.raises(asyncio.TimeoutError):
                await connector.fetch(ConnectorQuery(query="slow"))


# ---------------------------------------------------------------------------
# AC: enrichment failures are swallowed
# ---------------------------------------------------------------------------


class TestFetchEnrichmentFailures:
    @respx.mock
    async def test_failed_enrichment_skips_item(self) -> None:
        """Items whose enrichment raises an exception are skipped; others returned."""
        items = [_make_search_item(1), _make_search_item(2)]
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": items})
        )
        # file1.py: content fetch fails with 500
        respx.get(_content_url("src/file1.py")).mock(
            return_value=httpx.Response(500)
        )
        # file2.py: succeeds
        respx.get(_content_url("src/file2.py")).mock(
            return_value=httpx.Response(200, text="good content")
        )
        respx.get(_commits_url()).mock(
            return_value=httpx.Response(200, json=_make_commit_response())
        )

        connector = await _authenticated_connector()
        results = await connector.fetch(ConnectorQuery(query="content"))

        assert len(results) == 1
        assert results[0].source_id == "github:owner/repo:blobsha0002"

    @respx.mock
    async def test_all_enrichment_failures_returns_empty_list(self) -> None:
        """All enrichment failures return an empty list — no exception propagated."""
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": [_make_search_item(1)]})
        )
        respx.get(_content_url("src/file1.py")).mock(
            return_value=httpx.Response(404)
        )

        connector = await _authenticated_connector()
        results = await connector.fetch(ConnectorQuery(query="missing"))

        assert results == []


class TestFetchFallbackPathSearch:
    @respx.mock
    async def test_falls_back_to_repo_paths_when_code_search_is_empty(self) -> None:
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        respx.get(_trees_url("owner/repo", "main")).mock(
            return_value=httpx.Response(
                200,
                json=_tree_response(
                    [
                        (".github/skills/helper.py", "blob"),
                        ("docs/BRD.md", "blob"),
                        ("src/agents/nodes/retrieval.py", "blob"),
                        ("src/gateway/tools/enterprise/context_tools.py", "blob"),
                    ]
                ),
            )
        )
        respx.get(_content_url(".github/skills/helper.py")).mock(
            return_value=httpx.Response(200, text="helper code")
        )
        respx.get(_content_url("src/agents/nodes/retrieval.py")).mock(
            return_value=httpx.Response(200, text="retrieval_node code")
        )
        respx.get(_content_url("src/gateway/tools/enterprise/context_tools.py")).mock(
            return_value=httpx.Response(200, text="generate_context code")
        )
        respx.get(_commits_url()).mock(
            return_value=httpx.Response(200, json=_make_commit_response())
        )

        connector = await _authenticated_connector()
        results = await connector.fetch(
            ConnectorQuery(
                query=(
                    "Explain why the local ContextIQ repo retrieval is now working after the GitHub source fix. "
                    "Base the answer only on ContextIQ-retrieved evidence."
                ),
                max_results=2,
            )
        )

        assert len(results) == 2
        assert {result.source_id for result in results} == {
            "github:owner/repo:src/agents/nodes/retrieval.py",
            "github:owner/repo:src/gateway/tools/enterprise/context_tools.py",
        }
        assert all(result.metadata.extra["branch"] == "main" for result in results)


# ---------------------------------------------------------------------------
# AC: raises ConnectorAuthError before authenticate()
# ---------------------------------------------------------------------------


class TestFetchAuthError:
    async def test_raises_auth_error_when_not_authenticated(self) -> None:
        """fetch() raises ConnectorAuthError when authenticate() has not been called."""
        connector = GitHubConnector(_make_config())
        with pytest.raises(ConnectorAuthError):
            await connector.fetch(ConnectorQuery(query="test"))


# ---------------------------------------------------------------------------
# AC: len(results) <= query.max_results
# ---------------------------------------------------------------------------


class TestFetchMaxResults:
    @respx.mock
    async def test_results_capped_at_max_results(self) -> None:
        """Number of returned results never exceeds query.max_results."""
        items = [_make_search_item(i) for i in range(1, 6)]
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": items})
        )
        for i in range(1, 6):
            respx.get(_content_url(f"src/file{i}.py")).mock(
                return_value=httpx.Response(200, text=f"content{i}")
            )
        respx.get(_commits_url()).mock(
            return_value=httpx.Response(200, json=_make_commit_response())
        )

        connector = await _authenticated_connector()
        results = await connector.fetch(ConnectorQuery(query="code", max_results=3))

        assert len(results) <= 3


# ---------------------------------------------------------------------------
# GitHubContentClient unit tests
# ---------------------------------------------------------------------------


class TestGitHubContentClient:
    @respx.mock
    async def test_returns_excerpt_sha_and_timestamp(self) -> None:
        """fetch_content_and_commit() returns (excerpt, sha, datetime)."""
        config = _make_config()
        client_obj = GitHubContentClient(config)
        auth = {"Authorization": f"Bearer {_TOKEN}"}

        respx.get(f"{_BASE_URL}/repos/owner/repo/contents/src/main.py").mock(
            return_value=httpx.Response(200, text="print('hi')" * 300)
        )
        respx.get(f"{_BASE_URL}/repos/owner/repo/commits").mock(
            return_value=httpx.Response(
                200,
                json=_make_commit_response("deadbeef", "2024-06-01T12:00:00Z"),
            )
        )

        async with httpx.AsyncClient() as client:
            excerpt, sha, committed_at = await client_obj.fetch_content_and_commit(
                client=client,
                repo="owner/repo",
                file_path="src/main.py",
                auth_header=auth,
            )

        assert len(excerpt) <= 2000
        assert sha == "deadbeef"
        assert committed_at == datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)

    @respx.mock
    async def test_empty_commits_uses_now(self) -> None:
        """When no commits are returned, sha is '' and committed_at is close to now."""
        config = _make_config()
        client_obj = GitHubContentClient(config)
        auth = {"Authorization": f"Bearer {_TOKEN}"}

        respx.get(f"{_BASE_URL}/repos/owner/repo/contents/src/new.py").mock(
            return_value=httpx.Response(200, text="new file")
        )
        respx.get(f"{_BASE_URL}/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=[])
        )

        before = datetime.now(tz=UTC)
        async with httpx.AsyncClient() as client:
            excerpt, sha, committed_at = await client_obj.fetch_content_and_commit(
                client=client,
                repo="owner/repo",
                file_path="src/new.py",
                auth_header=auth,
            )
        after = datetime.now(tz=UTC)

        assert sha == ""
        assert excerpt == "new file"
        assert before <= committed_at <= after

    @respx.mock
    async def test_content_truncated_to_2000_chars(self) -> None:
        """Content exceeding 2000 characters is truncated."""
        config = _make_config()
        client_obj = GitHubContentClient(config)
        auth = {"Authorization": f"Bearer {_TOKEN}"}
        long_content = "x" * 5000

        respx.get(f"{_BASE_URL}/repos/owner/repo/contents/big.py").mock(
            return_value=httpx.Response(200, text=long_content)
        )
        respx.get(f"{_BASE_URL}/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=_make_commit_response())
        )

        async with httpx.AsyncClient() as client:
            excerpt, _, _ = await client_obj.fetch_content_and_commit(
                client=client,
                repo="owner/repo",
                file_path="big.py",
                auth_header=auth,
            )

        assert len(excerpt) == 2000
        assert excerpt == "x" * 2000

    @respx.mock
    async def test_fetch_content_and_commit_uses_branch_ref_when_provided(self) -> None:
        config = _make_config()
        client_obj = GitHubContentClient(config)
        auth = {"Authorization": f"Bearer {_TOKEN}"}

        respx.get(
            f"{_BASE_URL}/repos/owner/repo/contents/src/main.py",
            params={"ref": "feature/develop"},
        ).mock(return_value=httpx.Response(200, text="print('branch')"))
        respx.get(
            f"{_BASE_URL}/repos/owner/repo/commits",
            params={"path": "src/main.py", "per_page": 1, "sha": "feature/develop"},
        ).mock(
            return_value=httpx.Response(
                200,
                json=_make_commit_response("branchsha", "2024-06-02T12:00:00Z"),
            )
        )

        async with httpx.AsyncClient() as client:
            excerpt, sha, committed_at = await client_obj.fetch_content_and_commit(
                client=client,
                repo="owner/repo",
                file_path="src/main.py",
                auth_header=auth,
                branch="feature/develop",
            )

        assert excerpt == "print('branch')"
        assert sha == "branchsha"
        assert committed_at == datetime(2024, 6, 2, 12, 0, 0, tzinfo=UTC)
