"""
Unit tests for GitHubConnector.get_chunks() and GitHubContentClient.list_repo_files()
— the EP-008 indexing pipeline's full-repo content fetch (as opposed to
fetch()'s keyword-based GitHub Code Search).

All HTTP calls are mocked via respx; no live GitHub API calls in CI.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
import respx

from src.connector_sdk.exceptions import ConnectorAuthError
from src.connectors.github.config import GitHubConnectorConfig
from src.connectors.github.connector import GitHubConnector
from src.connectors.github.content_client import GitHubContentClient

_BASE_URL = "https://api.github.com"
_TOKEN = "ghp_test_token"
_SOURCE_ID = uuid4()
_TENANT_ID = "acme"


def _make_config(**overrides: object) -> GitHubConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": _BASE_URL,
        "request_timeout_s": 10.0,
        "repos": ["owner/repo"],
    }
    defaults.update(overrides)
    return GitHubConnectorConfig.model_validate(defaults)


def _trees_url(repo: str, branch: str) -> str:
    return f"{_BASE_URL}/repos/{repo}/git/trees/{branch}"


def _content_url(repo: str, path: str) -> str:
    return f"{_BASE_URL}/repos/{repo}/contents/{path}"


def _commits_url(repo: str) -> str:
    return f"{_BASE_URL}/repos/{repo}/commits"


def _tree_response(paths: list[tuple[str, str]]) -> dict:
    """paths: list of (path, type) tuples, e.g. [("README.md", "blob")]."""
    return {"tree": [{"path": p, "type": t} for p, t in paths]}


def _commit_response(sha: str = "commitabc") -> list:
    return [{"sha": sha, "commit": {"committer": {"date": "2024-01-15T10:00:00Z"}}}]


async def _authenticated_connector(config: GitHubConnectorConfig | None = None) -> GitHubConnector:
    connector = GitHubConnector(config or _make_config())
    with patch.object(
        connector._token_provider,
        "get_credential",
        new=AsyncMock(return_value=type("Cred", (), {"token": _TOKEN})()),
    ):
        await connector.authenticate()
    return connector


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# GitHubContentClient.list_repo_files
# ---------------------------------------------------------------------------


class TestListRepoFiles:
    @respx.mock
    async def test_lists_indexable_files_from_main_branch(self) -> None:
        respx.get(_trees_url("owner/repo", "main")).mock(
            return_value=httpx.Response(
                200,
                json=_tree_response(
                    [
                        ("README.md", "blob"),
                        ("src/app.py", "blob"),
                        ("assets/logo.png", "blob"),  # not indexable — filtered out
                        ("src", "tree"),  # a directory, not a blob — filtered out
                    ]
                ),
            )
        )
        client = GitHubContentClient(_make_config())
        async with httpx.AsyncClient() as http_client:
            paths = await client.list_repo_files(
                http_client, "owner/repo", {"Authorization": "Bearer x"}
            )

        assert paths == ["README.md", "src/app.py"]

    @respx.mock
    async def test_falls_back_to_master_branch_on_404(self) -> None:
        respx.get(_trees_url("owner/repo", "main")).mock(return_value=httpx.Response(404))
        respx.get(_trees_url("owner/repo", "master")).mock(
            return_value=httpx.Response(200, json=_tree_response([("README.md", "blob")]))
        )
        client = GitHubContentClient(_make_config())
        async with httpx.AsyncClient() as http_client:
            paths = await client.list_repo_files(
                http_client, "owner/repo", {"Authorization": "Bearer x"}
            )

        assert paths == ["README.md"]

    @respx.mock
    async def test_caps_at_max_files(self) -> None:
        many_files = [(f"file{i}.md", "blob") for i in range(10)]
        respx.get(_trees_url("owner/repo", "main")).mock(
            return_value=httpx.Response(200, json=_tree_response(many_files))
        )
        client = GitHubContentClient(_make_config())
        async with httpx.AsyncClient() as http_client:
            paths = await client.list_repo_files(
                http_client, "owner/repo", {"Authorization": "Bearer x"}, max_files=3
            )

        assert len(paths) == 3

    @respx.mock
    async def test_returns_empty_list_when_no_branch_exists(self) -> None:
        respx.get(_trees_url("owner/repo", "main")).mock(return_value=httpx.Response(404))
        respx.get(_trees_url("owner/repo", "master")).mock(return_value=httpx.Response(404))
        client = GitHubContentClient(_make_config())
        async with httpx.AsyncClient() as http_client:
            paths = await client.list_repo_files(
                http_client, "owner/repo", {"Authorization": "Bearer x"}
            )

        assert paths == []


# ---------------------------------------------------------------------------
# GitHubConnector.get_chunks
# ---------------------------------------------------------------------------


class TestGetChunks:
    @respx.mock
    async def test_raises_when_not_authenticated(self) -> None:
        connector = GitHubConnector(_make_config())
        with pytest.raises(ConnectorAuthError):
            await connector.get_chunks(_SOURCE_ID, _TENANT_ID)

    @respx.mock
    async def test_returns_one_chunk_per_file_with_source_and_tenant_id(self) -> None:
        respx.get(_trees_url("owner/repo", "main")).mock(
            return_value=httpx.Response(
                200, json=_tree_response([("README.md", "blob"), ("src/app.py", "blob")])
            )
        )
        respx.get(_content_url("owner/repo", "README.md")).mock(
            return_value=httpx.Response(200, text="# Hello")
        )
        respx.get(_content_url("owner/repo", "src/app.py")).mock(
            return_value=httpx.Response(200, text="print('hi')")
        )
        respx.get(_commits_url("owner/repo")).mock(
            return_value=httpx.Response(200, json=_commit_response())
        )

        connector = await _authenticated_connector()
        chunks = await connector.get_chunks(_SOURCE_ID, _TENANT_ID)

        assert len(chunks) == 2
        assert all(c.source_id == _SOURCE_ID for c in chunks)
        assert all(c.tenant_id == _TENANT_ID for c in chunks)
        assert all(c.document_id.startswith("github:owner/repo:") for c in chunks)
        assert {c.metadata["file_path"] for c in chunks} == {"README.md", "src/app.py"}
        assert all(c.text for c in chunks)
        assert all(c.token_count >= 1 for c in chunks)

    @respx.mock
    async def test_skips_empty_files(self) -> None:
        respx.get(_trees_url("owner/repo", "main")).mock(
            return_value=httpx.Response(200, json=_tree_response([("empty.md", "blob")]))
        )
        respx.get(_content_url("owner/repo", "empty.md")).mock(
            return_value=httpx.Response(200, text="   ")
        )
        respx.get(_commits_url("owner/repo")).mock(
            return_value=httpx.Response(200, json=_commit_response())
        )

        connector = await _authenticated_connector()
        chunks = await connector.get_chunks(_SOURCE_ID, _TENANT_ID)

        assert chunks == []

    @respx.mock
    async def test_skips_repo_that_fails_to_list(self) -> None:
        """One bad repo must not fail the whole batch when multiple repos are configured."""
        respx.get(_trees_url("owner/broken", "main")).mock(return_value=httpx.Response(500))
        respx.get(_trees_url("owner/good", "main")).mock(
            return_value=httpx.Response(200, json=_tree_response([("README.md", "blob")]))
        )
        respx.get(_content_url("owner/good", "README.md")).mock(
            return_value=httpx.Response(200, text="# Good repo")
        )
        respx.get(_commits_url("owner/good")).mock(
            return_value=httpx.Response(200, json=_commit_response())
        )

        connector = await _authenticated_connector(
            _make_config(repos=["owner/broken", "owner/good"])
        )
        chunks = await connector.get_chunks(_SOURCE_ID, _TENANT_ID)

        assert len(chunks) == 1
        assert chunks[0].metadata["repository"] == "owner/good"
