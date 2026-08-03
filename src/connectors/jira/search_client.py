"""
JiraSearchClient — JQL search against the Jira REST API v3.

TASK-US024-02: JiraConnector.fetch(), JQL Search Client, and health_check().

Provides:
- ``JiraIssueItem``: immutable Pydantic model for a single Jira issue row.
- ``JiraSearchClient``: async HTTP client that executes JQL queries via
  ``/rest/api/3/search`` and maps raw API responses to ``JiraIssueItem``.

Security note: user-supplied query strings are sanitised in ``_build_jql()``
before being embedded in the JQL ``text ~`` clause (JQL injection guard).
"""
from __future__ import annotations

from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict

from src.connectors.jira.config import JiraConnectorConfig


class JiraIssueItem(BaseModel):
    """Immutable representation of a single Jira issue from the REST API."""

    model_config = ConfigDict(frozen=True)

    issue_key: str
    summary: str
    status: str
    priority: str | None
    assignee: str | None
    description: str
    updated: datetime
    url: str


class JiraSearchClient:
    """Executes JQL queries against the Jira Cloud REST API v3."""

    def __init__(self, config: JiraConnectorConfig) -> None:
        self._config = config

    def _build_jql(self, query: str, filters: dict[str, str]) -> str:
        """
        Build a JQL string from the config template and optional free-text query.

        When ``filters`` contains ``"_jql_override"``, that value is returned
        directly, bypassing the default template.  This is used by the sync
        path to inject a time-scoped JQL clause (TASK-US024-04).

        Escapes single and double quotes in user input to prevent JQL injection
        before embedding inside the ``text ~ "…"`` clause.
        """
        if "_jql_override" in filters:
            return filters["_jql_override"]
        safe_query = query.replace("'", "\\'").replace('"', '\\"')[:500]
        projects = ", ".join(self._config.projects) or "ALL"
        base_jql = self._config.default_jql.format(projects=projects)
        if safe_query:
            return f'({base_jql}) AND text ~ "{safe_query}"'
        return base_jql

    async def search(
        self,
        query: str,
        auth_headers: dict[str, str],
        filters: dict[str, str],
        max_results: int = 50,
    ) -> list[JiraIssueItem]:
        """Execute a JQL search and return parsed issue items."""
        jql = self._build_jql(query, filters)
        params = {
            "jql": jql,
            "maxResults": min(max_results, 100),
            "fields": "summary,status,priority,assignee,description,updated",
        }
        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            resp = await client.get(
                f"{self._config.base_url}/rest/api/3/search",
                params=params,
                headers=auth_headers,
            )
            resp.raise_for_status()
            issues = resp.json().get("issues", [])

        return [self._parse_issue(i) for i in issues[:max_results]]

    def _parse_issue(self, raw: dict) -> JiraIssueItem:
        """Map a raw Jira REST API issue dict to a ``JiraIssueItem``."""
        fields = raw.get("fields", {})
        status = fields.get("status", {}).get("name", "Unknown")
        priority = (fields.get("priority") or {}).get("name")
        assignee = (fields.get("assignee") or {}).get("displayName")
        description = self._extract_description(fields.get("description"))
        updated_str = fields.get("updated", "")
        updated = datetime.fromisoformat(updated_str) if updated_str else None
        issue_key = raw.get("key", "")
        return JiraIssueItem(
            issue_key=issue_key,
            summary=fields.get("summary", ""),
            status=status,
            priority=priority,
            assignee=assignee,
            description=description,
            updated=updated,
            url=f"{self._config.base_url}/browse/{issue_key}",
        )

    @staticmethod
    def _extract_description(adf: dict | None) -> str:
        """
        Extract plain text from Atlassian Document Format (ADF).

        ADF is a nested JSON structure; this method recursively collects
        ``type="text"`` leaf nodes and joins them, capped at 1 000 characters.
        """
        if adf is None:
            return ""
        parts: list[str] = []

        def walk(node: dict) -> None:
            if node.get("type") == "text":
                parts.append(node.get("text", ""))
            for child in node.get("content", []):
                walk(child)

        walk(adf)
        return " ".join(parts)[:1000]
