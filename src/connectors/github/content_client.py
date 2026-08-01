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


def _path_priority(path: str) -> tuple[int, str]:
    lowered = path.lower()
    priority = 0
    if lowered.startswith("src/"):
        priority -= 40
    elif "/src/" in lowered:
        priority -= 12
    if lowered.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".kt", ".rb", ".cs")):
        priority -= 10
    if lowered.startswith(("src/agents/", "src/gateway/", "src/knowledge_sources/", "src/retrieval/")):
        priority -= 15
    if "/__tests__/" in lowered or ".test." in lowered or ".spec." in lowered:
        priority += 18
    if lowered.startswith("frontend/"):
        priority += 8
    if any(part in lowered for part in ("/node_modules/", "/dist/", "/build/", "/vendor/", "/coverage/", "/.venv/")):
        priority += 40
    if lowered.startswith(".github/"):
        priority += 25
    if lowered.startswith(".npm-package/") or lowered.startswith(".propel/"):
        priority += 20
    if lowered.startswith("docs/") or lowered.endswith((".md", ".mdx", ".rst")):
        priority += 10
    return (priority, lowered)


def _branch_priority(paths: list[str]) -> tuple[int, int, int, int]:
    src_count = sum(1 for path in paths if path.startswith("src/"))
    code_count = sum(
        1
        for path in paths
        if path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".kt", ".rb", ".cs"))
    )
    hidden_count = sum(1 for path in paths if path.startswith("."))
    doc_count = sum(1 for path in paths if path.startswith("docs/") or path.endswith((".md", ".mdx", ".rst")))
    return (src_count, code_count, -hidden_count, -doc_count)


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
        _selected_branch, paths = await self.list_repo_files_with_branch(
            client=client,
            repo=repo,
            auth_header=auth_header,
            branch=branch,
            max_files=max_files,
        )
        return paths

    async def list_repo_files_with_branch(
        self,
        client: httpx.AsyncClient,
        repo: str,
        auth_header: dict[str, str],
        branch: str = "main",
        max_files: int = 50,
    ) -> tuple[str, list[str]]:
        """
        Enumerate indexable file paths in *repo* via the Git Trees API
        (``GET /repos/{repo}/git/trees/{branch}?recursive=1``).

        Falls back to the ``master`` branch when ``main`` returns 404 (older
        repos). Results are filtered to a text-file extension allowlist and
        capped at *max_files* to bound sync duration and API usage.

        Returns:
            The selected branch name and up to *max_files* file paths. Returns
            ``("", [])`` if no candidate branch yields indexable files.
        """
        headers = {
            **auth_header,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        best_paths: list[str] = []
        best_branch = ""
        best_score: tuple[int, int, int, int] | None = None
        for candidate_branch in self._candidate_branches(branch):
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
            paths.sort(key=_path_priority)
            score = _branch_priority(paths)
            if best_score is None or score > best_score:
                best_paths = paths
                best_branch = candidate_branch
                best_score = score
            if score[0] > 0:
                break
        return best_branch, best_paths[:max_files]

    def _candidate_branches(self, branch: str) -> tuple[str, ...]:
        candidates = [branch, "main", "master", "develop", "dev", "feature/develop"]
        ordered: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in ordered:
                ordered.append(candidate)
        return tuple(ordered)

    async def fetch_content_and_commit(
        self,
        client: httpx.AsyncClient,
        repo: str,
        file_path: str,
        auth_header: dict[str, str],
        branch: str | None = None,
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
            params={"ref": branch} if branch else None,
            headers={**headers, "Accept": "application/vnd.github.raw+json"},
        )
        content_resp.raise_for_status()
        excerpt = content_resp.text[:2000]

        # Fetch last commit for this file
        commits_url = f"{self._config.base_url}/repos/{repo}/commits"
        commits_resp = await client.get(
            commits_url,
            params={
                "path": file_path,
                "per_page": 1,
                **({"sha": branch} if branch else {}),
            },
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
