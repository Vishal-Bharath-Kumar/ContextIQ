"""
Unit tests for TASK-US024-02: JiraSearchClient, JiraConnector.fetch(),
and JiraConnector.health_check().

All HTTP calls are mocked via ``respx``; no live Jira in CI.

Coverage targets (AC):
  - fetch() returns list[ConnectorResult] with source_id = "jira:{issue_key}"
  - metadata.extra contains issue_key, status, and priority
  - metadata.author is populated with the assignee's display name when present
  - fetch() raises asyncio.TimeoutError when total response exceeds 3 s
  - health_check() returns healthy=True when /myself returns 200
  - health_check() returns healthy=False and does not raise on HTTP 401
  - JQL injection: query '" OR project = SECRET' is escaped before embedding
  - ADF description with nested paragraph nodes extracts all leaf text
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
import respx
from httpx import Response

from src.connectors.jira.config import JiraConnectorConfig
from src.connectors.jira.connector import JiraConnector
from src.connectors.jira.search_client import JiraSearchClient

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_URL = "https://acme.atlassian.net"


def _make_config(**overrides: object) -> JiraConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": _BASE_URL,
        "email": "user@acme.com",
        "vault_addr": "https://vault.test:8200",
        "vault_role_id": "role",
        "vault_secret_id": "secret",
        "projects": ["OPS"],
    }
    defaults.update(overrides)
    return JiraConnectorConfig.model_validate(defaults)


def _make_raw_issue(
    key: str = "OPS-1234",
    summary: str = "Fix the thing",
    status: str = "In Progress",
    priority: str | None = "High",
    assignee: str | None = "Alice Smith",
    description_text: str = "Some description",
    updated: str = "2024-06-01T12:00:00.000+00:00",
) -> dict:
    """Build a minimal Jira REST API issue dict."""
    adf: dict | None = (
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description_text}],
                }
            ],
        }
        if description_text
        else None
    )
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status},
            "priority": {"name": priority} if priority else None,
            "assignee": {"displayName": assignee} if assignee else None,
            "description": adf,
            "updated": updated,
        },
    }


def _authenticated_connector() -> JiraConnector:
    """Return a JiraConnector with a pre-populated _credential (skips Vault)."""
    from src.connectors.jira.auth import JiraCredential

    config = _make_config()
    connector = JiraConnector(config=config)
    connector._credential = JiraCredential(token="test-token", email="user@acme.com")
    return connector


# ===========================================================================
# JiraSearchClient._extract_description
# ===========================================================================


class TestExtractDescription:
    def test_none_returns_empty_string(self) -> None:
        assert JiraSearchClient._extract_description(None) == ""

    def test_flat_text_node(self) -> None:
        adf = {"type": "doc", "content": [{"type": "text", "text": "Hello"}]}
        assert JiraSearchClient._extract_description(adf) == "Hello"

    def test_nested_paragraph_nodes(self) -> None:
        """ADF description with nested paragraph nodes extracts all leaf text (AC)."""
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "First"},
                        {"type": "text", "text": "Second"},
                    ],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Third"}],
                },
            ],
        }
        result = JiraSearchClient._extract_description(adf)
        assert "First" in result
        assert "Second" in result
        assert "Third" in result

    def test_truncated_at_1000_chars(self) -> None:
        adf = {"type": "doc", "content": [{"type": "text", "text": "x" * 2000}]}
        result = JiraSearchClient._extract_description(adf)
        assert len(result) <= 1000

    def test_non_text_nodes_ignored(self) -> None:
        adf = {
            "type": "doc",
            "content": [
                {"type": "hardBreak"},
                {"type": "text", "text": "Kept"},
            ],
        }
        assert JiraSearchClient._extract_description(adf) == "Kept"


# ===========================================================================
# JiraSearchClient._build_jql
# ===========================================================================


class TestBuildJql:
    def _client(self, **overrides: object) -> JiraSearchClient:
        return JiraSearchClient(_make_config(**overrides))

    def test_basic_jql_with_query(self) -> None:
        client = self._client(projects=["OPS", "INFRA"])
        jql = client._build_jql("deployment failed", {})
        assert 'text ~ "deployment failed"' in jql
        assert "OPS" in jql
        assert "INFRA" in jql

    def test_empty_query_omits_text_clause(self) -> None:
        client = self._client()
        jql = client._build_jql("", {})
        assert "text ~" not in jql

    def test_jql_injection_guard_double_quote(self) -> None:
        """Query '" OR project = SECRET' is escaped before CQL embedding (AC).

        The raw unescaped double-quote must not appear in the JQL so the
        injected text cannot break out of the ``text ~ "..."`` clause.
        """
        client = self._client()
        malicious = '" OR project = SECRET AND "'
        jql = client._build_jql(malicious, {})
        # Escaped form must be present
        assert '\\"' in jql
        # The JQL must not contain a bare (unescaped) double-quote that would
        # break out of the text ~ "…" clause — verify the output starts with
        # the expected prefix and wraps the value in escaped quotes.
        assert 'text ~ "' in jql
        # Confirm the surrounding text ~ "..." value does not contain an
        # unescaped standalone " that would allow JQL clause injection.
        # Extract what is between text ~ " and the closing "
        import re
        m = re.search(r'text ~ "(.*)"$', jql)
        assert m is not None, "Expected text ~ '...' clause not found"
        inner = m.group(1)
        # Inner value should not contain a raw unescaped double quote
        assert '"' not in inner.replace('\\"', '')

    def test_jql_injection_guard_single_quote(self) -> None:
        client = self._client()
        malicious = "x' OR project = SECRET"
        jql = client._build_jql(malicious, {})
        assert "\\'" in jql

    def test_query_truncated_at_500_chars(self) -> None:
        client = self._client()
        long_query = "a" * 600
        jql = client._build_jql(long_query, {})
        assert "a" * 501 not in jql


# ===========================================================================
# JiraSearchClient.search (via respx)
# ===========================================================================


class TestJiraSearchClientSearch:
    @respx.mock
    async def test_search_returns_parsed_items(self) -> None:
        config = _make_config()
        issue = _make_raw_issue()
        respx.get(f"{_BASE_URL}/rest/api/3/search").mock(
            return_value=Response(200, json={"issues": [issue]})
        )
        client = JiraSearchClient(config)
        results = await client.search("fix", {}, {}, max_results=10)

        assert len(results) == 1
        item = results[0]
        assert item.issue_key == "OPS-1234"
        assert item.summary == "Fix the thing"
        assert item.status == "In Progress"
        assert item.priority == "High"
        assert item.assignee == "Alice Smith"
        assert item.url == f"{_BASE_URL}/browse/OPS-1234"
        assert "Some description" in item.description

    @respx.mock
    async def test_search_respects_max_results_cap(self) -> None:
        config = _make_config()
        issues = [_make_raw_issue(key=f"OPS-{i}") for i in range(5)]
        respx.get(f"{_BASE_URL}/rest/api/3/search").mock(
            return_value=Response(200, json={"issues": issues})
        )
        client = JiraSearchClient(config)
        results = await client.search("query", {}, {}, max_results=3)
        assert len(results) == 3

    @respx.mock
    async def test_search_raises_on_http_error(self) -> None:
        config = _make_config()
        respx.get(f"{_BASE_URL}/rest/api/3/search").mock(
            return_value=Response(401, json={"error": "Unauthorized"})
        )
        client = JiraSearchClient(config)
        with pytest.raises(Exception):  # noqa: B017
            await client.search("query", {}, {})

    @respx.mock
    async def test_parse_issue_with_null_priority_and_assignee(self) -> None:
        config = _make_config()
        issue = _make_raw_issue(priority=None, assignee=None)
        respx.get(f"{_BASE_URL}/rest/api/3/search").mock(
            return_value=Response(200, json={"issues": [issue]})
        )
        client = JiraSearchClient(config)
        results = await client.search("query", {}, {})
        assert results[0].priority is None
        assert results[0].assignee is None


# ===========================================================================
# JiraConnector.fetch() (via respx)
# ===========================================================================


class TestJiraConnectorFetch:
    @respx.mock
    async def test_fetch_returns_connector_results(self) -> None:
        """fetch() returns list[ConnectorResult] with source_id = 'jira:{issue_key}' (AC)."""
        connector = _authenticated_connector()
        issue = _make_raw_issue()
        respx.get(f"{_BASE_URL}/rest/api/3/search").mock(
            return_value=Response(200, json={"issues": [issue]})
        )
        from src.connector_sdk.schemas.query import ConnectorQuery

        q = ConnectorQuery(query="deploy", max_results=10)
        results = await connector.fetch(q)

        assert len(results) == 1
        r = results[0]
        assert r.source_id == "jira:OPS-1234"
        assert "[OPS-1234]" in r.content
        assert "Fix the thing" in r.content

    @respx.mock
    async def test_fetch_metadata_extra_fields(self) -> None:
        """metadata.extra contains issue_key, status, and priority (AC)."""
        connector = _authenticated_connector()
        issue = _make_raw_issue(key="INFRA-99", status="Done", priority="Low")
        respx.get(f"{_BASE_URL}/rest/api/3/search").mock(
            return_value=Response(200, json={"issues": [issue]})
        )
        from src.connector_sdk.schemas.query import ConnectorQuery

        results = await connector.fetch(ConnectorQuery(query="test"))
        extra = results[0].metadata.extra
        assert extra["issue_key"] == "INFRA-99"
        assert extra["status"] == "Done"
        assert extra["priority"] == "Low"

    @respx.mock
    async def test_fetch_metadata_author_is_assignee(self) -> None:
        """metadata.author is populated with the assignee's display name (AC)."""
        connector = _authenticated_connector()
        issue = _make_raw_issue(assignee="Bob Jones")
        respx.get(f"{_BASE_URL}/rest/api/3/search").mock(
            return_value=Response(200, json={"issues": [issue]})
        )
        from src.connector_sdk.schemas.query import ConnectorQuery

        results = await connector.fetch(ConnectorQuery(query="test"))
        assert results[0].metadata.author == "Bob Jones"

    @respx.mock
    async def test_fetch_author_none_when_unassigned(self) -> None:
        connector = _authenticated_connector()
        issue = _make_raw_issue(assignee=None)
        respx.get(f"{_BASE_URL}/rest/api/3/search").mock(
            return_value=Response(200, json={"issues": [issue]})
        )
        from src.connector_sdk.schemas.query import ConnectorQuery

        results = await connector.fetch(ConnectorQuery(query="test"))
        assert results[0].metadata.author is None

    @respx.mock
    async def test_fetch_metadata_priority_none_becomes_string(self) -> None:
        connector = _authenticated_connector()
        issue = _make_raw_issue(priority=None)
        respx.get(f"{_BASE_URL}/rest/api/3/search").mock(
            return_value=Response(200, json={"issues": [issue]})
        )
        from src.connector_sdk.schemas.query import ConnectorQuery

        results = await connector.fetch(ConnectorQuery(query="test"))
        assert results[0].metadata.extra["priority"] == "None"

    async def test_fetch_raises_timeout_error(self) -> None:
        """fetch() raises asyncio.TimeoutError when total response exceeds 3 s (AC)."""
        connector = _authenticated_connector()

        async def _slow_search(*args, **kwargs) -> list:  # noqa: ANN002, ANN003
            await asyncio.sleep(10)
            return []

        with patch.object(JiraSearchClient, "search", side_effect=_slow_search):
            from src.connector_sdk.schemas.query import ConnectorQuery

            with pytest.raises(asyncio.TimeoutError):
                await connector.fetch(ConnectorQuery(query="test"))


# ===========================================================================
# JiraConnector.health_check() (via respx)
# ===========================================================================


class TestJiraConnectorHealthCheck:
    @respx.mock
    async def test_health_check_returns_true_on_200(self) -> None:
        """health_check() returns healthy=True when /myself returns 200 (AC)."""
        connector = _authenticated_connector()
        respx.get(f"{_BASE_URL}/rest/api/3/myself").mock(
            return_value=Response(200, json={"accountId": "acc-123"})
        )
        result = await connector.health_check()
        assert result.healthy is True
        assert "acc-123" in result.message

    @respx.mock
    async def test_health_check_returns_false_on_401(self) -> None:
        """health_check() returns healthy=False and does not raise on HTTP 401 (AC)."""
        connector = _authenticated_connector()
        respx.get(f"{_BASE_URL}/rest/api/3/myself").mock(
            return_value=Response(401, json={"message": "Unauthorized"})
        )
        result = await connector.health_check()
        assert result.healthy is False
        assert "401" in result.message

    async def test_health_check_returns_false_when_not_authenticated(self) -> None:
        config = _make_config()
        connector = JiraConnector(config=config)
        result = await connector.health_check()
        assert result.healthy is False
        assert "Not authenticated" in result.message

    @respx.mock
    async def test_health_check_returns_false_on_exception(self) -> None:
        """health_check() captures exceptions and returns healthy=False."""
        connector = _authenticated_connector()
        respx.get(f"{_BASE_URL}/rest/api/3/myself").mock(side_effect=Exception("conn refused"))
        result = await connector.health_check()
        assert result.healthy is False
        assert "conn refused" in result.message

    @respx.mock
    async def test_health_check_includes_checked_at(self) -> None:
        connector = _authenticated_connector()
        respx.get(f"{_BASE_URL}/rest/api/3/myself").mock(
            return_value=Response(200, json={"accountId": "x"})
        )
        result = await connector.health_check()
        assert result.checked_at is not None
        assert result.checked_at.tzinfo is not None
