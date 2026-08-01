"""
Unit tests for TASK-US022-02: GitHubSearchClient — Code Search API.

All HTTP calls are mocked via respx; no live GitHub API calls in CI.
asyncio.sleep is patched to avoid real delays in backoff tests.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from src.connectors.github.config import GitHubConnectorConfig
from src.connectors.github.search_client import GitHubFileItem, GitHubSearchClient

_SEARCH_URL = "https://api.github.com/search/code"
_AUTH_HEADER = {"Authorization": "Bearer ghp_test"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> GitHubConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": "https://api.github.com",
        "request_timeout_s": 10.0,
    }
    defaults.update(overrides)
    return GitHubConnectorConfig.model_validate(defaults)


def _make_api_item(n: int = 1) -> dict:
    """Return a minimal dict matching the GitHub Search API item shape."""
    return {
        "name": f"file{n}.py",
        "path": f"src/file{n}.py",
        "repository": "owner/repo",
        "html_url": f"https://github.com/owner/repo/blob/main/src/file{n}.py",
        "sha": f"abc{n:04d}",
        "url": f"https://api.github.com/repos/owner/repo/git/blobs/abc{n:04d}",
    }


def _make_real_api_item(n: int = 1) -> dict:
    return {
        "name": f"file{n}.py",
        "path": f"src/file{n}.py",
        "repository": {
            "name": "repo",
            "full_name": "owner/repo",
            "owner": {"login": "owner"},
        },
        "html_url": f"https://github.com/owner/repo/blob/main/src/file{n}.py",
        "sha": f"abc{n:04d}",
        "url": f"https://api.github.com/repos/owner/repo/git/blobs/abc{n:04d}",
    }


# ---------------------------------------------------------------------------
# search_code — happy path
# ---------------------------------------------------------------------------


class TestSearchCodeHappyPath:
    @respx.mock
    async def test_returns_github_file_item_models(self) -> None:
        """search_code() must return GitHubFileItem instances."""
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": [_make_api_item(1)]})
        )
        client = GitHubSearchClient(_make_config())
        result = await client.search_code("def main", [], _AUTH_HEADER)

        assert len(result) == 1
        assert isinstance(result[0], GitHubFileItem)

    @respx.mock
    async def test_returns_exactly_n_items_from_api(self) -> None:
        """A 200 response with 30 items must yield exactly 30 GitHubFileItem objects."""
        items = [_make_api_item(i) for i in range(1, 31)]
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": items})
        )
        client = GitHubSearchClient(_make_config())
        result = await client.search_code("auth", ["owner/repo"], _AUTH_HEADER)

        assert len(result) == 30
        assert all(isinstance(r, GitHubFileItem) for r in result)

    @respx.mock
    async def test_accepts_real_github_repository_object_shape(self) -> None:
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": [_make_real_api_item(1)]})
        )
        client = GitHubSearchClient(_make_config())
        result = await client.search_code("auth", ["owner/repo"], _AUTH_HEADER)

        assert len(result) == 1
        assert result[0].repository == "owner/repo"

    @respx.mock
    async def test_max_results_caps_output(self) -> None:
        """max_results=30 must return at most 30 items even when API returns more."""
        items = [_make_api_item(i) for i in range(1, 61)]  # 60 items from API
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": items})
        )
        client = GitHubSearchClient(_make_config())
        result = await client.search_code("token", [], _AUTH_HEADER, max_results=30)

        assert len(result) == 30

    @respx.mock
    async def test_empty_items_returns_empty_list(self) -> None:
        """A 200 response with an empty items array must return []."""
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        client = GitHubSearchClient(_make_config())
        result = await client.search_code("nothing", [], _AUTH_HEADER)

        assert result == []

    @respx.mock
    async def test_repo_qualifier_built_correctly(self) -> None:
        """repos param must be encoded as repo: qualifiers in the query string."""
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        client = GitHubSearchClient(_make_config())
        await client.search_code("secret", ["org/a", "org/b"], _AUTH_HEADER)

        last_request = respx.calls.last.request
        query_str = last_request.url.query.decode()
        # httpx percent-encodes `:` → %3A and `/` → %2F inside query values
        assert "repo%3Aorg%2Fa" in query_str
        assert "repo%3Aorg%2Fb" in query_str


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------


class TestPrometheusMetrics:
    @respx.mock
    async def test_latency_histogram_observed_on_success(self) -> None:
        """github_search_latency_seconds.observe() called after a successful call."""
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": [_make_api_item(1)]})
        )
        with patch(
            "src.connectors.github.search_client.github_search_latency_seconds"
        ) as mock_hist:
            client = GitHubSearchClient(_make_config())
            await client.search_code("test", [], _AUTH_HEADER)

        mock_hist.observe.assert_called_once()
        elapsed = mock_hist.observe.call_args[0][0]
        assert elapsed >= 0.0

    @respx.mock
    async def test_rate_limit_counter_incremented_on_429(self) -> None:
        """A 429 response must increment github_rate_limit_hits_total."""
        call_num = 0

        def _responses(request: httpx.Request) -> httpx.Response:
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"items": [_make_api_item(1)]})

        respx.get(_SEARCH_URL).mock(side_effect=_responses)

        mock_counter = MagicMock()
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        with (
            patch(
                "src.connectors.github.search_client.github_rate_limit_hits_total",
                mock_counter,
            ),
            patch(
                "src.connectors.github.search_client.github_search_latency_seconds"
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            client = GitHubSearchClient(_make_config())
            await client.search_code("test", [], _AUTH_HEADER)

        mock_counter.labels.assert_called_with(endpoint="search_code")
        mock_labels.inc.assert_called_once()


# ---------------------------------------------------------------------------
# Backoff / retry behaviour
# ---------------------------------------------------------------------------


class TestBackoffBehaviour:
    @respx.mock
    async def test_retry_after_header_determines_sleep_duration(self) -> None:
        """Retry-After: 5 header must cause asyncio.sleep(5.0) on a 429."""
        call_num = 0

        def _responses(request: httpx.Request) -> httpx.Response:
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return httpx.Response(429, headers={"Retry-After": "5"})
            return httpx.Response(200, json={"items": []})

        respx.get(_SEARCH_URL).mock(side_effect=_responses)

        with (
            patch(
                "src.connectors.github.search_client.github_rate_limit_hits_total"
            ),
            patch(
                "src.connectors.github.search_client.github_search_latency_seconds"
            ),
            patch(
                "src.connectors.github.search_client.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            client = GitHubSearchClient(_make_config())
            await client.search_code("test", [], _AUTH_HEADER)

        mock_sleep.assert_called_once_with(5.0)

    @respx.mock
    async def test_fallback_backoff_when_no_retry_after(self) -> None:
        """Without a Retry-After header, wait = 1 * 2^attempt (first attempt = 1.0 s)."""
        call_num = 0

        def _responses(request: httpx.Request) -> httpx.Response:
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return httpx.Response(429)  # no Retry-After header
            return httpx.Response(200, json={"items": []})

        respx.get(_SEARCH_URL).mock(side_effect=_responses)

        with (
            patch(
                "src.connectors.github.search_client.github_rate_limit_hits_total"
            ),
            patch(
                "src.connectors.github.search_client.github_search_latency_seconds"
            ),
            patch(
                "src.connectors.github.search_client.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            client = GitHubSearchClient(_make_config())
            await client.search_code("test", [], _AUTH_HEADER)

        mock_sleep.assert_called_once_with(1.0)  # 1.0 * 2^0 = 1.0

    @respx.mock
    async def test_max_retries_exhausted_raises_http_status_error(self) -> None:
        """After _MAX_RETRIES consecutive 429s, HTTPStatusError must be raised."""
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "0"})
        )

        with (
            patch(
                "src.connectors.github.search_client.github_rate_limit_hits_total"
            ),
            patch(
                "src.connectors.github.search_client.github_search_latency_seconds"
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            client = GitHubSearchClient(_make_config())
            with pytest.raises(httpx.HTTPStatusError, match="rate-limited"):
                await client.search_code("test", [], _AUTH_HEADER)

    @respx.mock
    async def test_non_429_4xx_raises_immediately(self) -> None:
        """A 403 Forbidden response must raise HTTPStatusError without retrying."""
        respx.get(_SEARCH_URL).mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )

        with patch(
            "src.connectors.github.search_client.github_search_latency_seconds"
        ):
            client = GitHubSearchClient(_make_config())
            with pytest.raises(httpx.HTTPStatusError):
                await client.search_code("test", [], _AUTH_HEADER)

        # Only one call should have been made (no retries)
        assert len(respx.calls) == 1

    @respx.mock
    async def test_backoff_capped_at_max(self) -> None:
        """Retry-After header value larger than _MAX_BACKOFF_S is capped at 60 s."""
        call_num = 0

        def _responses(request: httpx.Request) -> httpx.Response:
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return httpx.Response(429, headers={"Retry-After": "999"})
            return httpx.Response(200, json={"items": []})

        respx.get(_SEARCH_URL).mock(side_effect=_responses)

        with (
            patch(
                "src.connectors.github.search_client.github_rate_limit_hits_total"
            ),
            patch(
                "src.connectors.github.search_client.github_search_latency_seconds"
            ),
            patch(
                "src.connectors.github.search_client.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            client = GitHubSearchClient(_make_config())
            await client.search_code("test", [], _AUTH_HEADER)

        mock_sleep.assert_called_once_with(60.0)
