"""
Unit tests for TASK-US023-03: ConfluenceConnector.fetch() and strip_confluence_storage().

All ConfluenceCQLClient.search() calls are mocked via unittest.mock.patch;
no live Confluence or Vault in CI.

Coverage targets:
  - fetch() returns list[ConnectorResult] with source_id = confluence:{space}:{id}
  - metadata.extra contains page_title, space_key, page_id
  - metadata.author is populated when API returns a contributor name
  - strip_confluence_storage() removes <ac:structured-macro> tags and children
  - strip_confluence_storage() returns at most 5 000 characters
  - fetch() raises asyncio.TimeoutError when search exceeds 2 s (mocked)
  - fetch() raises ConnectorAuthError when called before authenticate()
  - filters["spaces"] overrides config.spaces for the request
  - empty body_excerpt produces empty content string
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.connector_sdk.exceptions import ConnectorAuthError
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connectors.confluence.config import ConfluenceConnectorConfig, ConfluenceDeploymentType
from src.connectors.confluence.connector import ConfluenceConnector
from src.connectors.confluence.cql_client import ConfluencePageItem
from src.connectors.confluence.html_stripper import strip_confluence_storage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LAST_MODIFIED = datetime(2024, 3, 15, 10, 30, 0, tzinfo=UTC)


def _make_config(**overrides: object) -> ConfluenceConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": "https://acme.atlassian.net",
        "deployment_type": "cloud",
        "email": "user@acme.com",
        "vault_role_id": "role",
        "vault_secret_id": "secret",
        "spaces": ["ENG"],
    }
    defaults.update(overrides)
    return ConfluenceConnectorConfig.model_validate(defaults)


def _make_page_item(**overrides: object) -> ConfluencePageItem:
    defaults: dict[str, object] = {
        "page_id": "123",
        "title": "Auth Flow",
        "space_key": "ENG",
        "url": "https://acme.atlassian.net/pages/viewpage.action?pageId=123",
        "body_excerpt": "<p>Hello world</p>",
        "author": "Alice",
        "last_modified": _LAST_MODIFIED,
    }
    defaults.update(overrides)
    return ConfluencePageItem.model_validate(defaults)


def _authenticated_connector(config: ConfluenceConnectorConfig | None = None) -> ConfluenceConnector:
    """Return a ConfluenceConnector with a faked credential already set."""
    from src.connectors.confluence.auth import ConfluenceCredential

    connector = ConfluenceConnector(config or _make_config())
    connector._credential = ConfluenceCredential(
        token="test-token",
        email="user@acme.com",
        deployment_type=ConfluenceDeploymentType.CLOUD,
    )
    return connector


def _make_query(**overrides: object) -> ConnectorQuery:
    defaults: dict[str, object] = {"query": "auth flow", "max_results": 10}
    defaults.update(overrides)
    return ConnectorQuery.model_validate(defaults)


# ---------------------------------------------------------------------------
# strip_confluence_storage
# ---------------------------------------------------------------------------


class TestStripConfluenceStorage:
    def test_plain_paragraph(self) -> None:
        result = strip_confluence_storage("<p>Hello world</p>")
        assert result == "Hello world"

    def test_removes_ac_structured_macro_tag_text(self) -> None:
        html = (
            "<p>Before</p>"
            "<ac:structured-macro ac:name='code'><ac:parameter>java</ac:parameter>some code</ac:structured-macro>"
            "<p>After</p>"
        )
        result = strip_confluence_storage(html)
        assert "some code" not in result
        assert "Before" in result
        assert "After" in result

    def test_skips_ac_parameter_content(self) -> None:
        html = "<ac:parameter>hidden param</ac:parameter><p>visible</p>"
        result = strip_confluence_storage(html)
        assert "hidden param" not in result
        assert "visible" in result

    def test_skips_style_tag_content(self) -> None:
        html = "<style>body { color: red; }</style><p>content</p>"
        result = strip_confluence_storage(html)
        assert "color" not in result
        assert "content" in result

    def test_skips_script_tag_content(self) -> None:
        html = "<script>alert('xss')</script><p>safe</p>"
        result = strip_confluence_storage(html)
        assert "alert" not in result
        assert "safe" in result

    def test_truncates_to_5000_characters(self) -> None:
        long_text = "A" * 10_000
        html = f"<p>{long_text}</p>"
        result = strip_confluence_storage(html)
        assert len(result) == 5000

    def test_empty_input_returns_empty_string(self) -> None:
        assert strip_confluence_storage("") == ""

    def test_whitespace_only_text_nodes_skipped(self) -> None:
        html = "<p>  </p><p>real</p>"
        result = strip_confluence_storage(html)
        assert result == "real"

    def test_multiple_paragraphs_joined_with_space(self) -> None:
        html = "<p>First</p><p>Second</p>"
        result = strip_confluence_storage(html)
        assert result == "First Second"

    def test_ri_attachment_tag_text_preserved(self) -> None:
        # ri: tags are unknown to html.parser and their data is emitted normally
        html = "<ri:attachment ri:filename='doc.pdf'>attachment text</ri:attachment>"
        result = strip_confluence_storage(html)
        assert "attachment text" in result

    def test_real_confluence_storage_snippet(self) -> None:
        html = (
            "<ac:structured-macro ac:name='code'>"
            "<ac:parameter ac:name='language'>python</ac:parameter>"
            "<ac:plain-text-body><![CDATA[def hello(): pass]]></ac:plain-text-body>"
            "</ac:structured-macro>"
            "<p>See the code above for an example.</p>"
        )
        result = strip_confluence_storage(html)
        assert "See the code above for an example." in result


# ---------------------------------------------------------------------------
# ConfluenceConnector.fetch() — auth guard
# ---------------------------------------------------------------------------


class TestFetchAuthGuard:
    @pytest.mark.asyncio
    async def test_raises_before_authenticate(self) -> None:
        connector = ConfluenceConnector(_make_config())
        with pytest.raises(ConnectorAuthError):
            await connector.fetch(_make_query())


# ---------------------------------------------------------------------------
# ConfluenceConnector.fetch() — successful path
# ---------------------------------------------------------------------------


class TestFetchSuccess:
    @pytest.mark.asyncio
    async def test_returns_connector_results(self) -> None:
        connector = _authenticated_connector()
        page = _make_page_item()

        with patch(
            "src.connectors.confluence.connector.ConfluenceCQLClient.search",
            new=AsyncMock(return_value=[page]),
        ):
            results = await connector.fetch(_make_query())

        assert len(results) == 1
        r = results[0]
        assert r.source_id == "confluence:ENG:123"
        assert r.content == "Hello world"

    @pytest.mark.asyncio
    async def test_source_id_format(self) -> None:
        connector = _authenticated_connector()
        page = _make_page_item(page_id="999", space_key="ARCH")

        with patch(
            "src.connectors.confluence.connector.ConfluenceCQLClient.search",
            new=AsyncMock(return_value=[page]),
        ):
            results = await connector.fetch(_make_query())

        assert results[0].source_id == "confluence:ARCH:999"

    @pytest.mark.asyncio
    async def test_metadata_extra_fields(self) -> None:
        connector = _authenticated_connector()
        page = _make_page_item(page_id="42", title="Design Doc", space_key="ARCH")

        with patch(
            "src.connectors.confluence.connector.ConfluenceCQLClient.search",
            new=AsyncMock(return_value=[page]),
        ):
            results = await connector.fetch(_make_query())

        extra = results[0].metadata.extra
        assert extra["page_title"] == "Design Doc"
        assert extra["space_key"] == "ARCH"
        assert extra["page_id"] == "42"

    @pytest.mark.asyncio
    async def test_metadata_author_populated(self) -> None:
        connector = _authenticated_connector()
        page = _make_page_item(author="Bob")

        with patch(
            "src.connectors.confluence.connector.ConfluenceCQLClient.search",
            new=AsyncMock(return_value=[page]),
        ):
            results = await connector.fetch(_make_query())

        assert results[0].metadata.author == "Bob"

    @pytest.mark.asyncio
    async def test_metadata_author_none_when_absent(self) -> None:
        connector = _authenticated_connector()
        page = _make_page_item(author=None)

        with patch(
            "src.connectors.confluence.connector.ConfluenceCQLClient.search",
            new=AsyncMock(return_value=[page]),
        ):
            results = await connector.fetch(_make_query())

        assert results[0].metadata.author is None

    @pytest.mark.asyncio
    async def test_empty_result_list(self) -> None:
        connector = _authenticated_connector()

        with patch(
            "src.connectors.confluence.connector.ConfluenceCQLClient.search",
            new=AsyncMock(return_value=[]),
        ):
            results = await connector.fetch(_make_query())

        assert results == []

    @pytest.mark.asyncio
    async def test_fetched_at_is_utc(self) -> None:
        connector = _authenticated_connector()
        page = _make_page_item()

        with patch(
            "src.connectors.confluence.connector.ConfluenceCQLClient.search",
            new=AsyncMock(return_value=[page]),
        ):
            results = await connector.fetch(_make_query())

        assert results[0].fetched_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_multiple_pages_returned(self) -> None:
        connector = _authenticated_connector()
        pages = [
            _make_page_item(page_id=str(i), title=f"Page {i}", space_key="ENG")
            for i in range(5)
        ]

        with patch(
            "src.connectors.confluence.connector.ConfluenceCQLClient.search",
            new=AsyncMock(return_value=pages),
        ):
            results = await connector.fetch(_make_query())

        assert len(results) == 5
        for i, r in enumerate(results):
            assert r.source_id == f"confluence:ENG:{i}"


# ---------------------------------------------------------------------------
# ConfluenceConnector.fetch() — spaces filter override
# ---------------------------------------------------------------------------


class TestFetchSpacesFilter:
    @pytest.mark.asyncio
    async def test_filters_spaces_override_config(self) -> None:
        config = _make_config(spaces=["ENG"])
        connector = _authenticated_connector(config)

        captured: list[list[str]] = []

        async def fake_search(
            self_inner: object,
            query: str,
            spaces: list[str],
            auth_headers: dict,
            max_results: int = 50,
            extra_cql: str = "",
        ) -> list:
            captured.append(spaces)
            return []

        with patch(
            "src.connectors.confluence.connector.ConfluenceCQLClient.search",
            new=fake_search,
        ):
            await connector.fetch(_make_query(filters={"spaces": "ARCH,DESIGN"}))

        assert captured[0] == ["ARCH", "DESIGN"]

    @pytest.mark.asyncio
    async def test_config_spaces_used_when_filter_absent(self) -> None:
        config = _make_config(spaces=["ENG", "DOCS"])
        connector = _authenticated_connector(config)

        captured: list[list[str]] = []

        async def fake_search(
            self_inner: object,
            query: str,
            spaces: list[str],
            auth_headers: dict,
            max_results: int = 50,
            extra_cql: str = "",
        ) -> list:
            captured.append(spaces)
            return []

        with patch(
            "src.connectors.confluence.connector.ConfluenceCQLClient.search",
            new=fake_search,
        ):
            await connector.fetch(_make_query())

        assert captured[0] == ["ENG", "DOCS"]


# ---------------------------------------------------------------------------
# ConfluenceConnector.fetch() — timeout
# ---------------------------------------------------------------------------


class TestFetchTimeout:
    @pytest.mark.asyncio
    async def test_raises_timeout_error_when_search_slow(self) -> None:
        connector = _authenticated_connector()

        async def slow_search(*args: object, **kwargs: object) -> list:
            await asyncio.sleep(10)
            return []

        with (
            patch(
                "src.connectors.confluence.connector.ConfluenceCQLClient.search",
                new=slow_search,
            ),
            patch(
                "src.connectors.confluence.connector.asyncio.wait_for",
                side_effect=asyncio.TimeoutError,
            ),
        ):
            with pytest.raises(asyncio.TimeoutError):
                await connector.fetch(_make_query())
