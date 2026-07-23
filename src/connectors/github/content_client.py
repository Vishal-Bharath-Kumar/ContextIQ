"""
GitHubContentClient — fetches raw file content and last-commit metadata.

TASK-US022-03: GitHubConnector.fetch() — Results Mapping to ConnectorResult.
"""
from __future__ import annotations

from datetime import UTC, datetime

import httpx

from src.connectors.github.config import GitHubConnectorConfig

# Extensions treated as indexable text for get_chunks()'s full-repo listing.
# GitHub's Search Code API (used by fetch()) requires search keywords and
# cannot enumerate "every file in the repo" -- the Git Trees API is used
# instead, so binary/generated files must be filtered client-side.
_INDEXABLE_EXTENSIONS = (
    ".md", ".mdx", ".rst", ".txt",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".kt", ".rb", ".cs",
    ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".sh",
)


class GitHubContentClient:
    """Fetches raw file content and last-commit metadata for a given file path."""

    def __init__(self, config: GitHubConnectorConfig) -> None:
        self._config = config

    async def list_repo_files(
        self,
        client: httpx.AsyncClient,
        repo: str,
        auth_header: dict[str, str],
        branch: str = "main",
        max_files: int = 50,
    ) -> list[str]:
        """
        Enumerate indexable file paths in *repo* via the Git Trees API
        (``GET /repos/{repo}/git/trees/{branch}?recursive=1``).

        Falls back to the ``master`` branch when ``main`` returns 404 (older
        repos). Results are filtered to a text-file extension allowlist and
        capped at *max_files* to bound sync duration and API usage.

        Returns:
            Up to *max_files* file paths. Empty list if neither branch exists
            or the repo has no indexable files.
        """
        headers = {
            **auth_header,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        for candidate_branch in (branch, "master"):
            resp = await client.get(
                f"{self._config.base_url}/repos/{repo}/git/trees/{candidate_branch}",
                params={"recursive": "1"},
                headers=headers,
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            tree = resp.json().get("tree", [])
            paths = [
                item["path"]
                for item in tree
                if item.get("type") == "blob"
                and item["path"].endswith(_INDEXABLE_EXTENSIONS)
            ]
            return paths[:max_files]
        return []

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
