"""
ConfluenceCQLClient — CQL Search API client with space filtering.

TASK-US023-02: Queries the Confluence REST v1 Content Search endpoint using
CQL (Confluence Query Language). Compatible with both Cloud and Data Center
deployments. Returns structured ConfluencePageItem results with CQL injection
protection.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from src.connectors.confluence.config import ConfluenceConnectorConfig, ConfluenceDeploymentType


class ConfluencePageItem(BaseModel):
    """One result from the Confluence CQL search response."""

    model_config = ConfigDict(frozen=True)

    page_id: str
    title: str
    space_key: str
    url: str  # absolute URL to the Confluence page
    body_excerpt: str  # truncated body storage value (≤ 5 000 chars raw)
    author: str | None  # display name; None if anonymous or unavailable
    last_modified: datetime


class ConfluenceCQLClient:
    """
    Queries the Confluence REST v1 Search endpoint.

    Compatible with both Cloud (/wiki/rest/api/content/search) and
    Data Center (/rest/api/content/search) via base_url + path mapping.
    """

    _CLOUD_SEARCH_PATH = "/wiki/rest/api/content/search"
    _DC_SEARCH_PATH = "/rest/api/content/search"

    def __init__(self, config: ConfluenceConnectorConfig) -> None:
        self._config = config

    def _search_url(self) -> str:
        path = (
            self._CLOUD_SEARCH_PATH
            if self._config.deployment_type == ConfluenceDeploymentType.CLOUD
            else self._DC_SEARCH_PATH
        )
        return f"{self._config.base_url.rstrip('/')}{path}"

    def _sanitise_cql_value(self, value: str) -> str:
        """
        Escape user-supplied text embedded in a CQL phrase query.

        CQL does not support parameterised queries; this guard prevents
        injection via crafted query strings by escaping backslash and
        double-quote characters and capping length to 500 chars.
        """
        sanitised = value.replace("\\", "\\\\").replace('"', '\\"')
        return sanitised[:500]

    def _build_cql(self, query: str, spaces: list[str], extra_clause: str = "") -> str:
        """
        Build a CQL expression with optional space filtering.

        Example output:
            type = "page" AND text ~ "auth flow" AND space in ("ENG","ARCH")
        """
        safe_query = self._sanitise_cql_value(query)
        parts: list[str] = ['type = "page"', f'text ~ "{safe_query}"']
        if spaces:
            space_list = ", ".join(f'"{s}"' for s in spaces)
            parts.append(f"space in ({space_list})")
        if extra_clause:
            parts.append(extra_clause)
        return " AND ".join(parts)

    async def search(
        self,
        query: str,
        spaces: list[str],
        auth_headers: dict[str, str],
        max_results: int = 50,
        extra_cql: str = "",
    ) -> list[ConfluencePageItem]:
        """
        Execute a CQL search and return at most *max_results* pages.

        The body excerpt is fetched as ``body.storage.value`` — raw Confluence
        storage format; stripping to plain text is the responsibility of the
        caller.

        Args:
            query: Full-text search term embedded in ``text ~ "..."``.
            spaces: Space keys to restrict the search (empty = all spaces).
            auth_headers: Pre-built HTTP auth headers (Basic or Bearer).
            max_results: Upper bound on returned items (default 50, capped at 50 per API page).
            extra_cql: Additional raw CQL clause appended with AND.

        Returns:
            List of ConfluencePageItem ordered by Confluence relevance ranking.
        """
        cql = self._build_cql(query, spaces, extra_cql)
        limit = min(max_results, 50)  # Confluence default max per request
        params: dict[str, str | int] = {
            "cql": cql,
            "limit": limit,
            "expand": "body.storage,version,space,history.lastUpdated",
        }
        items: list[ConfluencePageItem] = []

        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            start = 0
            while len(items) < max_results:
                params["start"] = start
                resp = await client.get(
                    self._search_url(), params=params, headers=auth_headers
                )
                resp.raise_for_status()
                data: Any = resp.json()
                results: list[Any] = data.get("results", [])
                if not results:
                    break
                for r in results:
                    items.append(self._parse_item(r))
                    if len(items) >= max_results:
                        break
                if data.get("size", 0) < limit:
                    break  # no more pages
                start += limit

        return items

    def _parse_item(self, r: Any) -> ConfluencePageItem:
        space_key = r.get("space", {}).get("key", "")
        base = self._config.base_url.rstrip("/")
        page_path = r.get("_links", {}).get("webui", "")
        if self._config.deployment_type == ConfluenceDeploymentType.CLOUD:
            url = f"{base}/wiki{page_path}"
        else:
            url = f"{base}{page_path}"
        body_raw = r.get("body", {}).get("storage", {}).get("value", "")
        body_excerpt = body_raw[:5000]

        last_updated_str = r.get("history", {}).get("lastUpdated", {}).get("when", "")
        last_modified = datetime.fromisoformat(last_updated_str) if last_updated_str else None

        contributor = r.get("history", {}).get("lastUpdated", {}).get("by", {})
        author = contributor.get("displayName") or contributor.get("username") or None

        return ConfluencePageItem(
            page_id=r.get("id", ""),
            title=r.get("title", ""),
            space_key=space_key,
            url=url,
            body_excerpt=body_excerpt,
            author=author,
            last_modified=last_modified,
        )
