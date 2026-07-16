"""
Unit tests for TASK-US023-02: ConfluenceCQLClient and ConfluencePageItem.

Uses respx to mock httpx requests — no live Confluence in CI.

Coverage targets:
  - search() returns ConfluencePageItem list with all fields populated
  - Cloud search URL: {base_url}/wiki/rest/api/content/search
  - Data Center search URL: {base_url}/rest/api/content/search
  - _build_cql() produces correct CQL with and without space clause
  - CQL injection: double-quote in query is escaped as \\\"
  - max_results=5 returns at most 5 items when API page has 50
  - Pagination stops when API returns fewer results than limit
  - URL construction differs between Cloud and Data Center
  - author falls back to username when displayName absent
  - author is None when no contributor info present
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
import respx
from httpx import Response

from src.connectors.confluence.config import ConfluenceConnectorConfig
from src.connectors.confluence.cql_client import ConfluenceCQLClient, ConfluencePageItem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLOUD_SEARCH_URL = "https://acme.atlassian.net/wiki/rest/api/content/search"
_DC_SEARCH_URL = "https://confluence.internal/rest/api/content/search"


def _make_cloud_config(**overrides: object) -> ConfluenceConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": "https://acme.atlassian.net",
        "deployment_type": "cloud",
        "email": "user@acme.com",
        "vault_role_id": "role",
        "vault_secret_id": "secret",
    }
    defaults.update(overrides)
    return ConfluenceConnectorConfig.model_validate(defaults)


def _make_dc_config(**overrides: object) -> ConfluenceConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": "https://confluence.internal",
        "deployment_type": "datacenter",
        "vault_role_id": "role",
        "vault_secret_id": "secret",
    }
    defaults.update(overrides)
    return ConfluenceConnectorConfig.model_validate(defaults)


def _page_result(
    page_id: str = "123",
    title: str = "Test Page",
    space_key: str = "ENG",
    webui: str = "/pages/viewpage.action?pageId=123",
    body: str = "<p>hello world</p>",
    when: str = "2024-03-15T10:30:00.000+00:00",
    display_name: str | None = "Alice",
    username: str | None = None,
) -> dict:
    contributor: dict = {}
    if display_name is not None:
        contributor["displayName"] = display_name
    if username is not None:
        contributor["username"] = username
    return {
        "id": page_id,
        "title": title,
        "space": {"key": space_key},
        "_links": {"webui": webui},
        "body": {"storage": {"value": body}},
        "history": {
            "lastUpdated": {
                "when": when,
                "by": contributor,
            }
        },
    }


def _search_response(results: list[dict], size: int | None = None) -> Response:
    payload = {
        "results": results,
        "size": size if size is not None else len(results),
    }
    return Response(200, content=json.dumps(payload).encode(), headers={"content-type": "application/json"})


_AUTH_HEADERS = {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# _build_cql
# ---------------------------------------------------------------------------


class TestBuildCql:
    def test_no_spaces(self) -> None:
        client = ConfluenceCQLClient(_make_cloud_config())
        cql = client._build_cql("auth flow", [])
        assert cql == 'type = "page" AND text ~ "auth flow"'

    def test_with_spaces(self) -> None:
        client = ConfluenceCQLClient(_make_cloud_config())
        cql = client._build_cql("auth flow", ["ENG", "ARCH"])
        assert cql == 'type = "page" AND text ~ "auth flow" AND space in ("ENG", "ARCH")'

    def test_with_extra_clause(self) -> None:
        client = ConfluenceCQLClient(_make_cloud_config())
        cql = client._build_cql("deploy", [], extra_clause='label = "release"')
        assert cql == 'type = "page" AND text ~ "deploy" AND label = "release"'

    def test_single_space(self) -> None:
        client = ConfluenceCQLClient(_make_cloud_config())
        cql = client._build_cql("test", ["DOCS"])
        assert 'space in ("DOCS")' in cql


# ---------------------------------------------------------------------------
# _sanitise_cql_value / CQL injection
# ---------------------------------------------------------------------------


class TestSanitiseCqlValue:
    def test_double_quote_escaped(self) -> None:
        client = ConfluenceCQLClient(_make_cloud_config())
        result = client._sanitise_cql_value('"arch" AND type = "blogpost"')
        assert result == '\\"arch\\" AND type = \\"blogpost\\"'

    def test_backslash_escaped(self) -> None:
        client = ConfluenceCQLClient(_make_cloud_config())
        result = client._sanitise_cql_value("path\\value")
        assert result == "path\\\\value"

    def test_length_capped_at_500(self) -> None:
        client = ConfluenceCQLClient(_make_cloud_config())
        long_input = "a" * 600
        assert len(client._sanitise_cql_value(long_input)) == 500

    def test_injection_in_cql(self) -> None:
        """Injection attempt ends up escaped inside the CQL phrase."""
        client = ConfluenceCQLClient(_make_cloud_config())
        cql = client._build_cql('"arch" AND type = "blogpost"', [])
        assert '\\"arch\\" AND type = \\"blogpost\\"' in cql


# ---------------------------------------------------------------------------
# _search_url
# ---------------------------------------------------------------------------


class TestSearchUrl:
    def test_cloud_url(self) -> None:
        client = ConfluenceCQLClient(_make_cloud_config())
        assert client._search_url() == _CLOUD_SEARCH_URL

    def test_datacenter_url(self) -> None:
        client = ConfluenceCQLClient(_make_dc_config())
        assert client._search_url() == _DC_SEARCH_URL

    def test_trailing_slash_stripped(self) -> None:
        config = _make_cloud_config(base_url="https://acme.atlassian.net/")
        client = ConfluenceCQLClient(config)
        assert client._search_url() == _CLOUD_SEARCH_URL


# ---------------------------------------------------------------------------
# search() — Cloud
# ---------------------------------------------------------------------------


class TestSearchCloud:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_page_items(self) -> None:
        respx.get(_CLOUD_SEARCH_URL).mock(
            return_value=_search_response([_page_result()])
        )
        client = ConfluenceCQLClient(_make_cloud_config())
        items = await client.search("auth flow", ["ENG"], _AUTH_HEADERS)
        assert len(items) == 1
        item = items[0]
        assert isinstance(item, ConfluencePageItem)
        assert item.page_id == "123"
        assert item.title == "Test Page"
        assert item.space_key == "ENG"
        assert item.author == "Alice"
        assert item.body_excerpt == "<p>hello world</p>"
        assert isinstance(item.last_modified, datetime)

    @pytest.mark.asyncio
    @respx.mock
    async def test_cloud_url_prefix(self) -> None:
        """Cloud item URLs use /wiki prefix."""
        respx.get(_CLOUD_SEARCH_URL).mock(
            return_value=_search_response([_page_result(webui="/pages/viewpage.action?pageId=123")])
        )
        client = ConfluenceCQLClient(_make_cloud_config())
        items = await client.search("test", [], _AUTH_HEADERS)
        assert items[0].url.startswith("https://acme.atlassian.net/wiki")

    @pytest.mark.asyncio
    @respx.mock
    async def test_max_results_respected(self) -> None:
        """max_results=5 returns at most 5 items even when API has more."""
        fifty_results = [_page_result(page_id=str(i), title=f"Page {i}") for i in range(50)]
        respx.get(_CLOUD_SEARCH_URL).mock(
            return_value=_search_response(fifty_results, size=50)
        )
        client = ConfluenceCQLClient(_make_cloud_config())
        items = await client.search("test", [], _AUTH_HEADERS, max_results=5)
        assert len(items) == 5

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_results(self) -> None:
        respx.get(_CLOUD_SEARCH_URL).mock(
            return_value=_search_response([])
        )
        client = ConfluenceCQLClient(_make_cloud_config())
        items = await client.search("nothing", [], _AUTH_HEADERS)
        assert items == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_pagination_stops_when_fewer_than_limit(self) -> None:
        """When API size < limit, no second request is made."""
        call_count = 0

        def handler(request: httpx.Request) -> Response:
            nonlocal call_count
            call_count += 1
            return _search_response([_page_result()], size=1)

        respx.get(_CLOUD_SEARCH_URL).mock(side_effect=handler)
        client = ConfluenceCQLClient(_make_cloud_config())
        items = await client.search("test", [], _AUTH_HEADERS, max_results=50)
        assert len(items) == 1
        assert call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_author_falls_back_to_username(self) -> None:
        result = _page_result(display_name=None, username="jdoe")
        respx.get(_CLOUD_SEARCH_URL).mock(
            return_value=_search_response([result])
        )
        client = ConfluenceCQLClient(_make_cloud_config())
        items = await client.search("test", [], _AUTH_HEADERS)
        assert items[0].author == "jdoe"

    @pytest.mark.asyncio
    @respx.mock
    async def test_author_none_when_absent(self) -> None:
        result = _page_result(display_name=None, username=None)
        respx.get(_CLOUD_SEARCH_URL).mock(
            return_value=_search_response([result])
        )
        client = ConfluenceCQLClient(_make_cloud_config())
        items = await client.search("test", [], _AUTH_HEADERS)
        assert items[0].author is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_body_excerpt_truncated_at_5000(self) -> None:
        long_body = "x" * 6000
        result = _page_result(body=long_body)
        respx.get(_CLOUD_SEARCH_URL).mock(
            return_value=_search_response([result])
        )
        client = ConfluenceCQLClient(_make_cloud_config())
        items = await client.search("test", [], _AUTH_HEADERS)
        assert len(items[0].body_excerpt) == 5000

    @pytest.mark.asyncio
    @respx.mock
    async def test_last_modified_parsed(self) -> None:
        respx.get(_CLOUD_SEARCH_URL).mock(
            return_value=_search_response([_page_result(when="2024-03-15T10:30:00.000+00:00")])
        )
        client = ConfluenceCQLClient(_make_cloud_config())
        items = await client.search("test", [], _AUTH_HEADERS)
        assert items[0].last_modified == datetime(2024, 3, 15, 10, 30, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# search() — Data Center
# ---------------------------------------------------------------------------


class TestSearchDataCenter:
    @pytest.mark.asyncio
    @respx.mock
    async def test_dc_url_used(self) -> None:
        respx.get(_DC_SEARCH_URL).mock(
            return_value=_search_response([_page_result()])
        )
        client = ConfluenceCQLClient(_make_dc_config())
        items = await client.search("deploy", ["OPS"], _AUTH_HEADERS)
        assert len(items) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_dc_url_prefix_no_wiki(self) -> None:
        """Data Center item URLs do NOT include /wiki prefix."""
        respx.get(_DC_SEARCH_URL).mock(
            return_value=_search_response(
                [_page_result(webui="/pages/viewpage.action?pageId=999")]
            )
        )
        client = ConfluenceCQLClient(_make_dc_config())
        items = await client.search("test", [], _AUTH_HEADERS)
        assert items[0].url == "https://confluence.internal/pages/viewpage.action?pageId=999"
        assert "/wiki" not in items[0].url

    @pytest.mark.asyncio
    @respx.mock
    async def test_dc_returns_all_fields(self) -> None:
        respx.get(_DC_SEARCH_URL).mock(
            return_value=_search_response([_page_result(page_id="42", title="DC Page", space_key="OPS")])
        )
        client = ConfluenceCQLClient(_make_dc_config())
        items = await client.search("test", ["OPS"], _AUTH_HEADERS)
        item = items[0]
        assert item.page_id == "42"
        assert item.title == "DC Page"
        assert item.space_key == "OPS"
