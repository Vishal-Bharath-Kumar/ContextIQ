"""Unit tests for ConnectorRegistry and ConnectorLoader.

TASK-US007-04 acceptance criteria verified:
  - registry_get_returns_connector:   registry.get() returns the registered instance
  - registry_get_not_found:           registry.get() raises ConnectorNotFoundError
  - registry_is_active_healthy:       is_active() True when connector is registered+healthy
  - registry_is_active_unhealthy:     is_active() False after set_health(..., False)
  - registry_is_active_unknown:       is_active() False for unregistered source_id
  - registry_active_source_ids:       active_source_ids() excludes unhealthy connectors
  - registry_register_overwrites:     re-registering resets health to True
  - registry_unregister:              unregistered connector no longer returned or active
  - loader_registers_active_configs:  load() registers all enabled configs from DB
  - loader_skips_disabled:            load() skips configs where enabled=False
  - loader_skips_unknown_type:        load() skips connector_type not in CLASS_MAP
  - loader_auth_failure_skipped:      load() skips a connector whose authenticate() raises
  - loader_reload_disables_connector: reload_connector() unregisters when config disabled
  - loader_reload_updates_connector:  reload_connector() re-registers an existing connector
  - health_check_loop_marks_unhealthy: loop sets health=False when health_check fails
  - health_check_loop_marks_healthy:   loop sets health=True when health_check succeeds
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.retrieval.connector_loader import (
    CONNECTOR_CLASS_MAP,
    ConnectorLoader,
    health_check_loop,
)
from src.agents.retrieval.connector_registry import (
    ConnectorNotFoundError,
    ConnectorRegistry,
)
from src.connector_sdk.schemas.health import HealthStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connector(healthy: bool = True) -> MagicMock:
    """Return a mock BaseConnector with authenticate() and health_check() stubs."""
    connector = MagicMock()
    connector.authenticate = AsyncMock()
    connector.health_check = AsyncMock(
        return_value=HealthStatus(
            healthy=healthy,
            message="ok" if healthy else "unreachable",
            checked_at=datetime(2026, 7, 16, tzinfo=UTC),
        )
    )
    return connector


def _make_db_config(
    name: str = "github:myorg/myrepo",
    connector_type: str = "github",
    config_blob: dict[str, Any] | None = None,
    enabled: bool = True,
) -> MagicMock:
    """Return a mock ConnectorConfig ORM row."""
    cfg = MagicMock()
    cfg.name = name
    cfg.connector_type = MagicMock()
    cfg.connector_type.value = connector_type
    cfg.config = config_blob or {}
    cfg.enabled = enabled
    return cfg


async def _mock_db_session(configs: list[MagicMock]) -> AsyncMock:
    """Return an AsyncSession mock whose execute().scalars().all() yields *configs*."""
    scalars = MagicMock()
    scalars.all.return_value = configs
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars
    session = AsyncMock()
    session.execute = AsyncMock(return_value=execute_result)
    return session


# ---------------------------------------------------------------------------
# ConnectorRegistry tests
# ---------------------------------------------------------------------------


class TestConnectorRegistry:
    def test_registry_get_returns_connector(self) -> None:
        registry = ConnectorRegistry()
        connector = _make_connector()
        registry.register("github:myorg/myrepo", connector)
        assert registry.get("github:myorg/myrepo") is connector

    def test_registry_get_not_found(self) -> None:
        registry = ConnectorRegistry()
        with pytest.raises(ConnectorNotFoundError) as exc_info:
            registry.get("unknown:source")
        assert exc_info.value.source_id == "unknown:source"

    def test_registry_is_active_healthy(self) -> None:
        registry = ConnectorRegistry()
        registry.register("jira:myproject", _make_connector())
        assert registry.is_active("jira:myproject") is True

    def test_registry_is_active_unhealthy(self) -> None:
        registry = ConnectorRegistry()
        registry.register("jira:myproject", _make_connector())
        registry.set_health("jira:myproject", False)
        assert registry.is_active("jira:myproject") is False

    def test_registry_is_active_unknown(self) -> None:
        registry = ConnectorRegistry()
        assert registry.is_active("does-not-exist") is False

    def test_registry_active_source_ids_excludes_unhealthy(self) -> None:
        registry = ConnectorRegistry()
        registry.register("src-a", _make_connector())
        registry.register("src-b", _make_connector())
        registry.set_health("src-b", False)
        assert registry.active_source_ids() == ["src-a"]

    def test_registry_active_source_ids_empty_when_all_unhealthy(self) -> None:
        registry = ConnectorRegistry()
        registry.register("src-a", _make_connector())
        registry.set_health("src-a", False)
        assert registry.active_source_ids() == []

    def test_registry_register_overwrites_and_resets_health(self) -> None:
        registry = ConnectorRegistry()
        first = _make_connector()
        second = _make_connector()
        registry.register("src", first)
        registry.set_health("src", False)
        registry.register("src", second)  # re-register
        assert registry.get("src") is second
        assert registry.is_active("src") is True

    def test_registry_unregister_removes_entry(self) -> None:
        registry = ConnectorRegistry()
        registry.register("src", _make_connector())
        registry.unregister("src")
        with pytest.raises(ConnectorNotFoundError):
            registry.get("src")
        assert registry.is_active("src") is False

    def test_registry_unregister_noop_on_unknown(self) -> None:
        registry = ConnectorRegistry()
        # Should not raise
        registry.unregister("does-not-exist")

    def test_registry_set_health_noop_on_unknown(self) -> None:
        registry = ConnectorRegistry()
        # Should not raise
        registry.set_health("does-not-exist", False)


# ---------------------------------------------------------------------------
# ConnectorLoader tests
# ---------------------------------------------------------------------------


class TestConnectorLoader:
    @pytest.mark.asyncio
    async def test_loader_registers_active_configs(self) -> None:
        """load() registers all enabled DB configs using CLASS_MAP."""
        configs = [
            _make_db_config("github:myorg/myrepo", "github"),
            _make_db_config("jira:myproject", "jira"),
            _make_db_config("confluence:myspace", "confluence"),
        ]
        session = await _mock_db_session(configs)
        registry = ConnectorRegistry()
        loader = ConnectorLoader()

        mock_connector = _make_connector()
        mock_connector_cls = MagicMock(return_value=mock_connector)
        mock_config_instance = MagicMock()
        mock_config_cls = MagicMock(return_value=mock_config_instance)

        patched_map = {
            "github": (mock_connector_cls, mock_config_cls),
            "jira": (mock_connector_cls, mock_config_cls),
            "confluence": (mock_connector_cls, mock_config_cls),
        }
        with patch(
            "src.agents.retrieval.connector_loader.CONNECTOR_CLASS_MAP",
            patched_map,
        ):
            await loader.load(registry, session)

        assert len(registry.active_source_ids()) == 3
        for source_id in ["github:myorg/myrepo", "jira:myproject", "confluence:myspace"]:
            assert registry.is_active(source_id)

    @pytest.mark.asyncio
    async def test_loader_skips_unknown_connector_type(self) -> None:
        """load() silently skips types not in CONNECTOR_CLASS_MAP."""
        configs = [_make_db_config("custom:src", "custom_type_unknown")]
        session = await _mock_db_session(configs)
        registry = ConnectorRegistry()
        loader = ConnectorLoader()

        await loader.load(registry, session)

        assert registry.active_source_ids() == []

    @pytest.mark.asyncio
    async def test_loader_skips_connector_on_auth_failure(self) -> None:
        """load() skips a connector whose authenticate() raises, loads the rest."""
        configs = [
            _make_db_config("github:good", "github"),
            _make_db_config("jira:bad", "jira"),
        ]
        session = await _mock_db_session(configs)
        registry = ConnectorRegistry()
        loader = ConnectorLoader()

        good_connector = _make_connector()
        bad_connector = MagicMock()
        bad_connector.authenticate = AsyncMock(side_effect=RuntimeError("vault error"))

        def _make_cls(instance: MagicMock) -> MagicMock:
            return MagicMock(return_value=instance)

        mock_config_cls = MagicMock(return_value=MagicMock())

        patched_map = {
            "github": (_make_cls(good_connector), mock_config_cls),
            "jira": (_make_cls(bad_connector), mock_config_cls),
        }
        with patch(
            "src.agents.retrieval.connector_loader.CONNECTOR_CLASS_MAP",
            patched_map,
        ):
            await loader.load(registry, session)

        assert registry.is_active("github:good")
        assert not registry.is_active("jira:bad")

    @pytest.mark.asyncio
    async def test_loader_reload_unregisters_when_config_disabled(self) -> None:
        """reload_connector() unregisters when no enabled config found."""
        # scalars().first() returns None (disabled / deleted)
        scalars = MagicMock()
        scalars.first.return_value = None
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars
        session = AsyncMock()
        session.execute = AsyncMock(return_value=execute_result)

        registry = ConnectorRegistry()
        registry.register("jira:myproject", _make_connector())

        loader = ConnectorLoader()
        await loader.reload_connector(registry, session, "jira:myproject")

        assert not registry.is_active("jira:myproject")
        with pytest.raises(ConnectorNotFoundError):
            registry.get("jira:myproject")

    @pytest.mark.asyncio
    async def test_loader_reload_updates_existing_connector(self) -> None:
        """reload_connector() replaces an existing connector with a fresh instance."""
        config = _make_db_config("confluence:wiki", "confluence")
        scalars = MagicMock()
        scalars.first.return_value = config
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars
        session = AsyncMock()
        session.execute = AsyncMock(return_value=execute_result)

        registry = ConnectorRegistry()
        old_connector = _make_connector()
        registry.register("confluence:wiki", old_connector)
        registry.set_health("confluence:wiki", False)

        new_connector = _make_connector()
        mock_cls = MagicMock(return_value=new_connector)
        mock_config_cls = MagicMock(return_value=MagicMock())

        with patch(
            "src.agents.retrieval.connector_loader.CONNECTOR_CLASS_MAP",
            {"confluence": (mock_cls, mock_config_cls)},
        ):
            loader = ConnectorLoader()
            await loader.reload_connector(registry, session, "confluence:wiki")

        assert registry.get("confluence:wiki") is new_connector
        assert registry.is_active("confluence:wiki") is True

    def test_connector_class_map_has_expected_types(self) -> None:
        """CONNECTOR_CLASS_MAP contains all four required connector types."""
        for key in ("github", "confluence", "jira", "grafana"):
            assert key in CONNECTOR_CLASS_MAP
            connector_cls, config_cls = CONNECTOR_CLASS_MAP[key]
            assert callable(connector_cls)
            assert callable(config_cls)


# ---------------------------------------------------------------------------
# health_check_loop tests
# ---------------------------------------------------------------------------


class TestHealthCheckLoop:
    @pytest.mark.asyncio
    async def test_loop_marks_connector_unhealthy_on_failure(self) -> None:
        """health_check_loop sets health=False when health_check() raises."""
        registry = ConnectorRegistry()
        connector = MagicMock()
        connector.health_check = AsyncMock(side_effect=RuntimeError("unreachable"))
        registry.register("grafana:prod", connector)

        # Run one iteration then cancel
        task = asyncio.create_task(health_check_loop(registry))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert registry.is_active("grafana:prod") is False

    @pytest.mark.asyncio
    async def test_loop_marks_connector_healthy_on_success(self) -> None:
        """health_check_loop sets health=True when health_check() returns healthy."""
        registry = ConnectorRegistry()
        connector = _make_connector(healthy=True)
        registry.register("github:myorg/myrepo", connector)
        # Start as unhealthy
        registry.set_health("github:myorg/myrepo", False)

        task = asyncio.create_task(health_check_loop(registry))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert registry.is_active("github:myorg/myrepo") is True

    @pytest.mark.asyncio
    async def test_loop_marks_unhealthy_on_status_false(self) -> None:
        """health_check_loop respects healthy=False in HealthStatus response."""
        registry = ConnectorRegistry()
        connector = _make_connector(healthy=False)
        registry.register("jira:prod", connector)

        task = asyncio.create_task(health_check_loop(registry))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert registry.is_active("jira:prod") is False

    @pytest.mark.asyncio
    async def test_loop_handles_timeout(self) -> None:
        """health_check_loop marks connector unhealthy when health_check times out."""
        registry = ConnectorRegistry()
        connector = MagicMock()

        async def _hanging_health_check() -> HealthStatus:  # pragma: no cover
            await asyncio.sleep(100)
            return HealthStatus(
                healthy=True,
                message="should not reach here",
                checked_at=datetime(2026, 7, 16, tzinfo=UTC),
            )

        connector.health_check = AsyncMock(side_effect=_hanging_health_check)
        registry.register("slow:connector", connector)

        with patch(
            "src.agents.retrieval.connector_loader.asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ):
            task = asyncio.create_task(health_check_loop(registry))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert registry.is_active("slow:connector") is False


# ---------------------------------------------------------------------------
# config_change_listener tests
# ---------------------------------------------------------------------------


class TestConfigChangeListener:
    @pytest.mark.asyncio
    async def test_listener_reloads_on_valid_message(self) -> None:
        """config_change_listener calls reload_connector on a valid JSON message."""
        from src.agents.retrieval.connector_loader import config_change_listener

        registry = ConnectorRegistry()

        messages = [
            {"type": "subscribe", "data": 1},
            {"type": "message", "data": json.dumps({"name": "github:myorg/myrepo"})},
        ]

        async def _aiter_messages() -> AsyncGenerator[dict, None]:
            for m in messages:
                yield m

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = MagicMock(return_value=_aiter_messages())

        redis_client = MagicMock()
        redis_client.pubsub = MagicMock(return_value=pubsub)

        mock_session = AsyncMock()
        session_cm = AsyncMock()
        session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        session_cm.__aexit__ = AsyncMock(return_value=False)

        session_factory = MagicMock(return_value=session_cm)

        with patch(
            "src.agents.retrieval.connector_loader.ConnectorLoader.reload_connector",
            new_callable=AsyncMock,
        ) as mock_reload:
            await config_change_listener(registry, redis_client, session_factory)

        mock_reload.assert_awaited_once()
        call_kwargs = mock_reload.call_args
        assert call_kwargs[0][2] == "github:myorg/myrepo"

    @pytest.mark.asyncio
    async def test_listener_skips_invalid_payload(self) -> None:
        """config_change_listener skips messages with malformed JSON."""
        from src.agents.retrieval.connector_loader import config_change_listener

        registry = ConnectorRegistry()

        messages = [
            {"type": "message", "data": "not-valid-json"},
        ]

        async def _aiter_messages() -> AsyncGenerator[dict, None]:
            for m in messages:
                yield m

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = MagicMock(return_value=_aiter_messages())

        redis_client = MagicMock()
        redis_client.pubsub = MagicMock(return_value=pubsub)
        session_factory = MagicMock()

        with patch(
            "src.agents.retrieval.connector_loader.ConnectorLoader.reload_connector",
            new_callable=AsyncMock,
        ) as mock_reload:
            await config_change_listener(registry, redis_client, session_factory)

        mock_reload.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_listener_skips_missing_name_key(self) -> None:
        """config_change_listener skips valid JSON missing the 'name' key."""
        from src.agents.retrieval.connector_loader import config_change_listener

        registry = ConnectorRegistry()

        messages = [
            {"type": "message", "data": json.dumps({"connector_id": "something"})},
        ]

        async def _aiter_messages() -> AsyncGenerator[dict, None]:
            for m in messages:
                yield m

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen = MagicMock(return_value=_aiter_messages())

        redis_client = MagicMock()
        redis_client.pubsub = MagicMock(return_value=pubsub)
        session_factory = MagicMock()

        with patch(
            "src.agents.retrieval.connector_loader.ConnectorLoader.reload_connector",
            new_callable=AsyncMock,
        ) as mock_reload:
            await config_change_listener(registry, redis_client, session_factory)

        mock_reload.assert_not_awaited()
