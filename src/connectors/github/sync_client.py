"""
GitHubCommitsClient — fetches files changed in a repository since a given timestamp.

TASK-US022-04: GitHubConnector.sync() — Incremental Sync with `since` Parameter.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from src.connectors.github.config import GitHubConnectorConfig


class GitHubCommitsClient:
    """
    Fetches the list of file paths changed in a GitHub repository since a
    given ISO-8601 timestamp, using the ``/repos/{repo}/commits`` endpoint.

    Args:
        config: Connector configuration (base URL, timeout, etc.).
    """

    def __init__(self, config: GitHubConnectorConfig) -> None:
        self._config = config

    async def fetch_changed_files(
        self,
        repo: str,
        since: datetime,
        auth_header: dict[str, str],
    ) -> list[str]:
        """
        Return a deduplicated list of file paths changed in *repo* since *since*.

        Uses the ``/repos/{repo}/commits`` endpoint with the ``since``
        ISO-8601 parameter, then fetches each commit's detail to obtain the
        full file list.  Pagination is handled automatically via the ``page``
        parameter.

        Args:
            repo:        ``"owner/repo"`` string.
            since:       UTC-aware datetime; commits at or after this point
                         are included.
            auth_header: ``{"Authorization": "Bearer <token>"}`` dict.

        Returns:
            Deduplicated list of relative file paths (e.g. ``"src/main.py"``).

        Raises:
            httpx.HTTPStatusError: when the GitHub API returns a non-2xx status.
        """
        headers = {
            **auth_header,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        changed: set[str] = set()

        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            page = 1
            while True:
                resp = await client.get(
                    f"{self._config.base_url}/repos/{repo}/commits",
                    params={"since": since.isoformat(), "per_page": 100, "page": page},
                    headers=headers,
                )
                resp.raise_for_status()
                commits = resp.json()
                if not commits:
                    break
                for commit in commits:
                    detail_resp = await client.get(commit["url"], headers=headers)
                    detail_resp.raise_for_status()
                    for file_entry in detail_resp.json().get("files", []):
                        changed.add(file_entry["filename"])
                page += 1

        return list(changed)
