"""
Unit tests for TASK-US022-04: GitHubConnector.sync() — Incremental Sync.

All external I/O (PostgreSQL, GitHub API, Kafka) is mocked via AsyncMock / respx.
No live connections are made in CI.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from src.connector_sdk.exceptions import ConnectorAuthError
from src.connector_sdk.schemas.sync import SyncResult
from src.connectors.github.config import GitHubConnectorConfig
from src.connectors.github.connector import GitHubConnector
from src.connectors.github.sync_client import GitHubCommitsClient
from src.connectors.github.sync_store import ConnectorSyncStore

_BASE_URL = "https://api.github.com"
_TOKEN = "ghp_sync_test_token"
_REPO = "owner/repo"
_COMMITS_URL = f"{_BASE_URL}/repos/{_REPO}/commits"
_COMMIT_DETAIL_URL = f"{_BASE_URL}/repos/{_REPO}/commits/abc123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> GitHubConnectorConfig:
    defaults: dict[str, object] = {
        "base_url": _BASE_URL,
        "request_timeout_s": 10.0,
        "repos": [_REPO],
        "default_days": 30,
    }
    defaults.update(overrides)
    return GitHubConnectorConfig.model_validate(defaults)


async def _authenticated_connector(
    config: GitHubConnectorConfig | None = None,
    session: object = None,
) -> GitHubConnector:
    """Return a GitHubConnector with authenticate() already called."""
    connector = GitHubConnector(config=config or _make_config(), session=session)
    with patch.object(
        connector._token_provider,
        "get_credential",
        new=AsyncMock(return_value=type("Cred", (), {"token": _TOKEN})()),
    ):
        await connector.authenticate()
    return connector


def _mock_sync_store(last_sync_at: datetime | None = None) -> AsyncMock:
    store = AsyncMock(spec=ConnectorSyncStore)
    store.get_last_sync_at.return_value = last_sync_at
    store.set_last_sync_at.return_value = None
    return store


def _mock_commits_client(changed_files: list[str] | None = None) -> AsyncMock:
    client = AsyncMock(spec=GitHubCommitsClient)
    client.fetch_changed_files.return_value = changed_files or ["src/main.py", "README.md"]
    return client


# ---------------------------------------------------------------------------
# ConnectorSyncStore unit tests
# ---------------------------------------------------------------------------


class TestConnectorSyncStore:
    async def test_get_last_sync_at_returns_none_when_no_row(self) -> None:
        session = AsyncMock()
        row_mock = MagicMock()
        row_mock.fetchone.return_value = None
        session.execute.return_value = row_mock

        store = ConnectorSyncStore(session)
        result = await store.get_last_sync_at("github")

        assert result is None
        session.execute.assert_called_once()

    async def test_get_last_sync_at_returns_datetime_when_row_exists(self) -> None:
        ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        session = AsyncMock()
        row_mock = MagicMock()
        row_mock.fetchone.return_value = (ts,)
        session.execute.return_value = row_mock

        store = ConnectorSyncStore(session)
        result = await store.get_last_sync_at("github")

        assert result == ts

    async def test_set_last_sync_at_executes_upsert_and_commits(self) -> None:
        session = AsyncMock()
        ts = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)

        store = ConnectorSyncStore(session)
        await store.set_last_sync_at("github", ts)

        session.execute.assert_called_once()
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# GitHubCommitsClient unit tests
# ---------------------------------------------------------------------------


class TestGitHubCommitsClient:
    @respx.mock
    async def test_fetch_changed_files_returns_deduplicated_paths(self) -> None:
        since = datetime(2024, 1, 1, tzinfo=UTC)
        config = _make_config()

        def _commits_side_effect(request: httpx.Request) -> httpx.Response:
            page = request.url.params.get("page", "1")
            if page == "1":
                return httpx.Response(200, json=[{"url": _COMMIT_DETAIL_URL}])
            return httpx.Response(200, json=[])

        respx.get(_COMMITS_URL).mock(side_effect=_commits_side_effect)
        # Commit detail: two files (one duplicated across pages)
        respx.get(_COMMIT_DETAIL_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "files": [
                        {"filename": "src/main.py"},
                        {"filename": "src/main.py"},  # duplicate — must be deduped
                        {"filename": "README.md"},
                    ]
                },
            )
        )

        client = GitHubCommitsClient(config)
        result = await client.fetch_changed_files(
            repo=_REPO,
            since=since,
            auth_header={"Authorization": f"Bearer {_TOKEN}"},
        )

        assert sorted(result) == ["README.md", "src/main.py"]

    @respx.mock
    async def test_fetch_changed_files_stops_on_empty_page(self) -> None:
        """Pagination loop must stop when GitHub returns an empty list."""
        since = datetime(2024, 1, 1, tzinfo=UTC)
        config = _make_config()

        respx.get(_COMMITS_URL).mock(return_value=httpx.Response(200, json=[]))

        client = GitHubCommitsClient(config)
        result = await client.fetch_changed_files(
            repo=_REPO,
            since=since,
            auth_header={"Authorization": f"Bearer {_TOKEN}"},
        )

        assert result == []

    @respx.mock
    async def test_fetch_changed_files_raises_on_http_error(self) -> None:
        since = datetime(2024, 1, 1, tzinfo=UTC)
        config = _make_config()

        respx.get(_COMMITS_URL).mock(return_value=httpx.Response(401))

        client = GitHubCommitsClient(config)
        with pytest.raises(httpx.HTTPStatusError):
            await client.fetch_changed_files(
                repo=_REPO,
                since=since,
                auth_header={"Authorization": f"Bearer {_TOKEN}"},
            )


# ---------------------------------------------------------------------------
# GitHubConnector.sync() — acceptance criteria
# ---------------------------------------------------------------------------


class TestGitHubConnectorSync:
    async def test_sync_raises_when_not_authenticated(self) -> None:
        """AC: sync() raises ConnectorAuthError when authenticate() has not been called."""
        connector = GitHubConnector(config=_make_config(), session=AsyncMock())
        with pytest.raises(ConnectorAuthError):
            await connector.sync()

    async def test_sync_uses_last_sync_at_when_prior_record_exists(self) -> None:
        """AC: sync() calls commits API with since=last_sync_at when prior sync exists."""
        prior_ts = datetime(2024, 5, 1, tzinfo=UTC)
        mock_store = _mock_sync_store(last_sync_at=prior_ts)
        mock_commits = _mock_commits_client(["src/main.py"])
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector()

        with (
            patch(
                "src.connectors.github.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.github.connector.GitHubCommitsClient",
                return_value=mock_commits,
            ),
            patch(
                "src.connectors.github.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
        ):
            result = await connector.sync()

        mock_commits.fetch_changed_files.assert_called_once()
        call_kwargs = mock_commits.fetch_changed_files.call_args
        assert call_kwargs.kwargs["since"] == prior_ts or call_kwargs.args[1] == prior_ts
        assert result.items_processed == 1

    async def test_sync_defaults_to_default_days_when_no_prior_record(self) -> None:
        """AC: sync() defaults to now - default_days when no prior sync record exists."""
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_commits = _mock_commits_client(["file.py"])
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        config = _make_config(default_days=7)
        connector = await _authenticated_connector(config=config)

        with (
            patch(
                "src.connectors.github.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.github.connector.GitHubCommitsClient",
                return_value=mock_commits,
            ),
            patch(
                "src.connectors.github.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
        ):
            result = await connector.sync()

        call_since: datetime = mock_commits.fetch_changed_files.call_args.kwargs.get(
            "since"
        ) or mock_commits.fetch_changed_files.call_args.args[1]

        # The fallback should be approximately now - 7 days
        expected_floor = datetime.now(tz=UTC) - timedelta(days=8)
        assert call_since > expected_floor
        assert result.items_processed == 1

    async def test_sync_writes_last_sync_at_after_completion(self) -> None:
        """AC: sync() writes the new last_sync_at to connector_sync_state after completion."""
        mock_store = _mock_sync_store(last_sync_at=None)
        mock_commits = _mock_commits_client([])
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector()

        with (
            patch(
                "src.connectors.github.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.github.connector.GitHubCommitsClient",
                return_value=mock_commits,
            ),
            patch(
                "src.connectors.github.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
        ):
            await connector.sync()

        mock_store.set_last_sync_at.assert_called_once()
        args = mock_store.set_last_sync_at.call_args
        connector_id = args.args[0] if args.args else args.kwargs.get("connector_id")
        assert connector_id == "github"

    async def test_sync_returns_sync_result_with_non_negative_counts(self) -> None:
        """AC: sync() returns SyncResult with items_processed >= 0 and items_failed >= 0."""
        mock_store = _mock_sync_store()
        mock_commits = _mock_commits_client(["a.py", "b.py", "c.py"])
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector()

        with (
            patch(
                "src.connectors.github.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.github.connector.GitHubCommitsClient",
                return_value=mock_commits,
            ),
            patch(
                "src.connectors.github.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
        ):
            result = await connector.sync()

        assert isinstance(result, SyncResult)
        assert result.items_processed >= 0
        assert result.items_failed >= 0
        assert result.items_processed == 3

    async def test_sync_captures_per_repo_errors_without_aborting(self) -> None:
        """AC: per-repo errors are captured in SyncResult.errors; sync does not abort."""
        mock_store = _mock_sync_store()
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        failing_commits = AsyncMock(spec=GitHubCommitsClient)
        failing_commits.fetch_changed_files.side_effect = RuntimeError("network timeout")

        config = _make_config(repos=["owner/repo1", "owner/repo2"])
        connector = await _authenticated_connector(config=config)

        with (
            patch(
                "src.connectors.github.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.github.connector.GitHubCommitsClient",
                return_value=failing_commits,
            ),
            patch(
                "src.connectors.github.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
        ):
            result = await connector.sync()

        assert result.items_failed == 2
        assert len(result.errors) == 2
        assert all("RuntimeError" in e for e in result.errors)
        # Sync completed despite errors — last_sync_at was still written
        mock_store.set_last_sync_at.assert_called_once()

    async def test_sync_emits_kafka_event_on_completion(self) -> None:
        """AC: _emit_sync_event() sends a message to contextiq.source.sync topic."""
        mock_store = _mock_sync_store()
        mock_commits = _mock_commits_client(["x.py"])
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector()

        with (
            patch(
                "src.connectors.github.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.github.connector.GitHubCommitsClient",
                return_value=mock_commits,
            ),
            patch(
                "src.connectors.github.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
        ):
            await connector.sync()

        mock_producer.send_and_wait.assert_called_once()
        call_args = mock_producer.send_and_wait.call_args
        topic = call_args.args[0] if call_args.args else call_args.kwargs.get("topic")
        assert topic == "contextiq.source.sync"

    async def test_sync_last_sync_at_in_result_is_utc_aware(self) -> None:
        """SyncResult.last_sync_at must be a UTC-aware datetime."""
        mock_store = _mock_sync_store()
        mock_commits = _mock_commits_client([])
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        connector = await _authenticated_connector()

        with (
            patch(
                "src.connectors.github.connector.ConnectorSyncStore",
                return_value=mock_store,
            ),
            patch(
                "src.connectors.github.connector.GitHubCommitsClient",
                return_value=mock_commits,
            ),
            patch(
                "src.connectors.github.connector.get_kafka_producer",
                new=AsyncMock(return_value=mock_producer),
            ),
        ):
            result = await connector.sync()

        assert result.last_sync_at.tzinfo is not None
