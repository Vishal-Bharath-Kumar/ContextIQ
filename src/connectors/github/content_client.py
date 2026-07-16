"""
GitHubContentClient — fetches raw file content and last-commit metadata.

TASK-US022-03: GitHubConnector.fetch() — Results Mapping to ConnectorResult.
"""
from __future__ import annotations

from datetime import UTC, datetime

import httpx

from src.connectors.github.config import GitHubConnectorConfig


class GitHubContentClient:
    """Fetches raw file content and last-commit metadata for a given file path."""

    def __init__(self, config: GitHubConnectorConfig) -> None:
        self._config = config

    async def fetch_content_and_commit(
        self,
        client: httpx.AsyncClient,
        repo: str,
        file_path: str,
        auth_header: dict[str, str],
    ) -> tuple[str, str, datetime]:
        """
        Returns (content_excerpt, last_commit_sha, committed_at).

        Content excerpt is truncated to 2000 chars — full content is indexed by EP-008.
        """
        headers = {
            **auth_header,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        # Fetch file content (raw)
        content_url = f"{self._config.base_url}/repos/{repo}/contents/{file_path}"
        content_resp = await client.get(
            content_url,
            headers={**headers, "Accept": "application/vnd.github.raw+json"},
        )
        content_resp.raise_for_status()
        excerpt = content_resp.text[:2000]

        # Fetch last commit for this file
        commits_url = f"{self._config.base_url}/repos/{repo}/commits"
        commits_resp = await client.get(
            commits_url,
            params={"path": file_path, "per_page": 1},
            headers=headers,
        )
        commits_resp.raise_for_status()
        commits = commits_resp.json()

        if commits:
            sha = commits[0]["sha"]
            committed_at = datetime.fromisoformat(
                commits[0]["commit"]["committer"]["date"].replace("Z", "+00:00")
            )
        else:
            sha = ""
            committed_at = datetime.now(tz=UTC)

        return excerpt, sha, committed_at
