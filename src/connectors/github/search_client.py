"""
GitHubSearchClient — HTTP client for the GitHub Code Search API.

TASK-US022-02: GitHubSearchClient with exponential backoff on 429 responses.
"""
from __future__ import annotations

import asyncio
import time

import httpx
from pydantic import BaseModel, ConfigDict

from src.connectors.github.config import GitHubConnectorConfig
from src.connectors.github.metrics import (
    github_rate_limit_hits_total,
    github_search_latency_seconds,
)

_MAX_BACKOFF_S = 60.0
_BACKOFF_BASE_S = 1.0
_MAX_RETRIES = 5


class GitHubFileItem(BaseModel):
    """One item from the GitHub Search API 'items' array."""

    model_config = ConfigDict(frozen=True)

    name: str
    path: str
    repository: str  # "owner/repo"
    html_url: str
    sha: str  # blob SHA
    url: str  # API URL for full content fetch


class GitHubSearchClient:
    """Queries the GitHub Search API for code with rate-limit backoff."""

    def __init__(self, config: GitHubConnectorConfig) -> None:
        self._config = config

    async def search_code(
        self,
        query: str,
        repos: list[str],
        auth_header: dict[str, str],
        max_results: int = 50,
    ) -> list[GitHubFileItem]:
        """
        Query the GitHub Search API: GET /search/code.

        Returns at most *max_results* items.
        Raises ``httpx.HTTPStatusError`` for non-retryable errors (4xx except 429).
        """
        repo_qualifier = " ".join(f"repo:{r}" for r in repos) if repos else ""
        q = f"{query} {repo_qualifier}".strip()
        params = {"q": q, "per_page": min(max_results, 100)}

        t0 = time.perf_counter()
        items = await self._get_with_backoff(
            url=f"{self._config.base_url}/search/code",
            params=params,
            auth_header=auth_header,
            endpoint="search_code",
        )
        elapsed = time.perf_counter() - t0
        github_search_latency_seconds.observe(elapsed)

        return [GitHubFileItem.model_validate(item) for item in items[:max_results]]

    async def _get_with_backoff(
        self,
        url: str,
        params: dict,
        auth_header: dict[str, str],
        endpoint: str,
    ) -> list[dict]:
        headers = {
            **auth_header,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        attempt = 0
        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            while attempt < _MAX_RETRIES:
                response = await client.get(url, params=params, headers=headers)

                if response.status_code == 429:
                    github_rate_limit_hits_total.labels(endpoint=endpoint).inc()
                    retry_after = float(
                        response.headers.get(
                            "Retry-After", _BACKOFF_BASE_S * (2**attempt)
                        )
                    )
                    wait = min(retry_after, _MAX_BACKOFF_S)
                    await asyncio.sleep(wait)
                    attempt += 1
                    continue

                response.raise_for_status()
                return response.json().get("items", [])

        raise httpx.HTTPStatusError(
            f"GitHub API rate-limited after {_MAX_RETRIES} retries",
            request=response.request,
            response=response,
        )
