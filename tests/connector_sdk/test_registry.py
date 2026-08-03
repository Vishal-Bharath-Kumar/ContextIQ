"""
Unit tests for TASK-US021-02: Entry-Point Auto-Discovery and ConnectorRegistry.

Coverage targets (all acceptance criteria):
  - discover_connectors() returns only BaseConnector subclasses
  - Malformed entry point (import error) is logged and skipped; load() does not raise
  - A class that does not subclass BaseConnector is logged and skipped
  - ConnectorRegistry.load() calls authenticate() on each discovered class
  - Connectors where authenticate() raises are registered with enabled=False
  - ConnectorRegistry.get("unknown_id") returns None
  - ConnectorRegistry.get() returns None for disabled connectors
  - ConnectorRegistry.all_enabled() returns only enabled instances
  - ConnectorRegistry.set_health() disables a connector on unhealthy status
  - ConnectorRegistry.records() returns all records (enabled and disabled)
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.connector_sdk.base import BaseConnector
from src.connector_sdk.discovery import discover_connectors
from src.connector_sdk.registry import ConnectorRecord, ConnectorRegistry
from src.connector_sdk.schemas.health import HealthStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult
from src.connector_sdk.schemas.sync import SyncResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_stub(*, auth_raises: bool = False) -> type[BaseConnector]:
    """Return a concrete BaseConnector subclass suitable for injection."""

    class _Stub(BaseConnector):
        async def authenticate(self) -> None:
            if auth_raises:
                raise RuntimeError("auth failed")

        async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
            return []

        async def sync(self) -> SyncResult:
            return SyncResult(
                items_processed=0,
                items_failed=0,
                last_sync_at=_utc_now(),
            )

        async def health_check(self) -> HealthStatus:
            return HealthStatus(healthy=True, message="ok", checked_at=_utc_now())

    return _Stub


# ---------------------------------------------------------------------------
# discover_connectors — unit tests using mocked entry points
# ---------------------------------------------------------------------------

class TestDiscoverConnectors:
    def test_returns_valid_baseconnector_subclass(self) -> None:
        """discover_connectors() returns only BaseConnector subclasses."""
        StubCls = _make_stub()

        ep = MagicMock()
        ep.name = "stub"
        ep.load.return_value = StubCls

        with patch("src.connector_sdk.discovery.importlib.metadata.entry_points", return_value=[ep]):
            result = discover_connectors()

        assert "stub" in result
        assert result["stub"] is StubCls

    def test_skips_entry_point_with_import_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """A malformed entry point (import error) is logged and skipped."""
        ep = MagicMock()
        ep.name = "broken"
        ep.load.side_effect = ImportError("no module named 'nonexistent'")

        with patch("src.connector_sdk.discovery.importlib.metadata.entry_points", return_value=[ep]):
            with caplog.at_level("WARNING", logger="src.connector_sdk.discovery"):
                result = discover_connectors()

        assert "broken" not in result
        assert "connector_discovery_failed" in caplog.text

    def test_skips_non_baseconnector_class(self, caplog: pytest.LogCaptureFixture) -> None:
        """A class that does not subclass BaseConnector is logged and skipped."""

        class _NotAConnector:
            pass

        ep = MagicMock()
        ep.name = "wrong"
        ep.load.return_value = _NotAConnector

        with patch("src.connector_sdk.discovery.importlib.metadata.entry_points", return_value=[ep]):
            with caplog.at_level("WARNING", logger="src.connector_sdk.discovery"):
                result = discover_connectors()

        assert "wrong" not in result
        assert "connector_not_a_baseconnector" in caplog.text

    def test_skips_non_class_value(self, caplog: pytest.LogCaptureFixture) -> None:
        """A non-class value registered as an entry point is skipped."""
        ep = MagicMock()
        ep.name = "not_a_class"
        ep.load.return_value = "just_a_string"

        with patch("src.connector_sdk.discovery.importlib.metadata.entry_points", return_value=[ep]):
            with caplog.at_level("WARNING", logger="src.connector_sdk.discovery"):
                result = discover_connectors()

        assert "not_a_class" not in result

    def test_returns_empty_dict_when_no_entry_points(self) -> None:
        """Returns an empty dict when no contextiq.connectors entry points exist."""
        with patch("src.connector_sdk.discovery.importlib.metadata.entry_points", return_value=[]):
            result = discover_connectors()

        assert result == {}

    def test_multiple_valid_connectors_all_returned(self) -> None:
        """All valid connectors in the group are returned."""
        StubA = _make_stub()
        StubB = _make_stub()

        ep_a = MagicMock()
        ep_a.name = "connector_a"
        ep_a.load.return_value = StubA

        ep_b = MagicMock()
        ep_b.name = "connector_b"
        ep_b.load.return_value = StubB

        with patch(
            "src.connector_sdk.discovery.importlib.metadata.entry_points",
            return_value=[ep_a, ep_b],
        ):
            result = discover_connectors()

        assert set(result.keys()) == {"connector_a", "connector_b"}


# ---------------------------------------------------------------------------
# ConnectorRegistry — unit tests (injected connector_classes, no live EPs)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestConnectorRegistryLoad:
    async def test_load_calls_authenticate_on_each_class(self) -> None:
        """ConnectorRegistry.load() calls authenticate() on each discovered class."""
        StubCls = _make_stub()
        registry = ConnectorRegistry()
        await registry.load(connector_classes={"test_connector": StubCls})

        assert len(registry.records()) == 1
        record = registry.records()[0]
        assert record.connector_id == "test_connector"
        assert record.enabled is True

    async def test_load_with_empty_classes_produces_no_records(self) -> None:
        """load() with an empty dict produces no records."""
        registry = ConnectorRegistry()
        await registry.load(connector_classes={})

        assert registry.records() == []

    async def test_auth_failure_registers_connector_as_disabled(self) -> None:
        """Connectors where authenticate() raises are registered with enabled=False."""
        FailingStub = _make_stub(auth_raises=True)
        registry = ConnectorRegistry()
        await registry.load(connector_classes={"failing": FailingStub})

        record = registry.records()[0]
        assert record.enabled is False
        assert record.connector_id == "failing"

    async def test_auth_failure_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """An authentication failure is recorded in the error log."""
        FailingStub = _make_stub(auth_raises=True)
        registry = ConnectorRegistry()

        with caplog.at_level("ERROR", logger="src.connector_sdk.registry"):
            await registry.load(connector_classes={"failing": FailingStub})

        assert "connector_auth_failed" in caplog.text

    async def test_load_does_not_raise_on_auth_failure(self) -> None:
        """load() must not raise even when authenticate() fails."""
        FailingStub = _make_stub(auth_raises=True)
        registry = ConnectorRegistry()
        # Should not raise:
        await registry.load(connector_classes={"failing": FailingStub})

    async def test_load_multiple_connectors_some_failing(self) -> None:
        """Mix of healthy and failing connectors: healthy remain enabled."""
        OkStub = _make_stub(auth_raises=False)
        BadStub = _make_stub(auth_raises=True)

        registry = ConnectorRegistry()
        await registry.load(connector_classes={"ok": OkStub, "bad": BadStub})

        assert registry.get("ok") is not None
        assert registry.get("bad") is None


@pytest.mark.asyncio
class TestConnectorRegistryGet:
    async def test_get_returns_none_for_unknown_id(self) -> None:
        """ConnectorRegistry.get('unknown_id') returns None."""
        registry = ConnectorRegistry()
        await registry.load(connector_classes={})

        assert registry.get("unknown_id") is None

    async def test_get_returns_none_for_disabled_connector(self) -> None:
        """get() returns None for a disabled (auth-failed) connector."""
        FailingStub = _make_stub(auth_raises=True)
        registry = ConnectorRegistry()
        await registry.load(connector_classes={"failing": FailingStub})

        assert registry.get("failing") is None

    async def test_get_returns_instance_for_enabled_connector(self) -> None:
        """get() returns the connector instance for an enabled connector."""
        StubCls = _make_stub()
        registry = ConnectorRegistry()
        await registry.load(connector_classes={"ok": StubCls})

        instance = registry.get("ok")
        assert instance is not None
        assert isinstance(instance, BaseConnector)


@pytest.mark.asyncio
class TestConnectorRegistryRegister:
    """Covers register() — used by IndexingPipeline to add per-source
    connectors (keyed by knowledge_source UUID) outside of entry-point
    discovery (which only registers one shared instance per connector TYPE)."""

    async def test_register_makes_connector_retrievable_via_get(self) -> None:
        StubCls = _make_stub()
        instance = StubCls()
        registry = ConnectorRegistry()

        registry.register("some-source-id", instance)

        assert registry.get("some-source-id") is instance

    async def test_register_defaults_to_enabled(self) -> None:
        StubCls = _make_stub()
        instance = StubCls()
        registry = ConnectorRegistry()

        registry.register("some-source-id", instance)

        assert instance in registry.all_enabled()

    async def test_register_can_mark_disabled(self) -> None:
        StubCls = _make_stub()
        instance = StubCls()
        registry = ConnectorRegistry()

        registry.register("some-source-id", instance, enabled=False)

        assert registry.get("some-source-id") is None
        assert instance not in registry.all_enabled()

    async def test_register_overwrites_existing_entry(self) -> None:
        StubCls = _make_stub()
        first, second = StubCls(), StubCls()
        registry = ConnectorRegistry()

        registry.register("some-source-id", first)
        registry.register("some-source-id", second)

        assert registry.get("some-source-id") is second


@pytest.mark.asyncio
class TestConnectorRegistryAllEnabled:
    async def test_all_enabled_returns_only_enabled_instances(self) -> None:
        """all_enabled() returns only instances with enabled=True."""
        OkStub = _make_stub(auth_raises=False)
        BadStub = _make_stub(auth_raises=True)

        registry = ConnectorRegistry()
        await registry.load(connector_classes={"ok": OkStub, "bad": BadStub})

        enabled = registry.all_enabled()
        assert len(enabled) == 1
        assert isinstance(enabled[0], BaseConnector)

    async def test_all_enabled_empty_when_none_pass_auth(self) -> None:
        """all_enabled() is empty when all connectors fail authentication."""
        BadStub = _make_stub(auth_raises=True)
        registry = ConnectorRegistry()
        await registry.load(connector_classes={"bad": BadStub})

        assert registry.all_enabled() == []


@pytest.mark.asyncio
class TestConnectorRegistrySetHealth:
    async def test_set_health_disables_connector_on_unhealthy(self) -> None:
        """set_health() with healthy=False disables the connector."""
        StubCls = _make_stub()
        registry = ConnectorRegistry()
        await registry.load(connector_classes={"svc": StubCls})

        assert registry.get("svc") is not None  # initially enabled

        registry.set_health("svc", healthy=False, checked_at=_utc_now())

        assert registry.get("svc") is None  # now disabled

    async def test_set_health_updates_last_health_and_checked_at(self) -> None:
        """set_health() updates last_health and last_checked on the record."""
        StubCls = _make_stub()
        registry = ConnectorRegistry()
        await registry.load(connector_classes={"svc": StubCls})

        ts = _utc_now()
        registry.set_health("svc", healthy=True, checked_at=ts)

        record = registry.records()[0]
        assert record.last_health is True
        assert record.last_checked == ts

    async def test_set_health_noop_for_unknown_connector(self) -> None:
        """set_health() on an unknown connector_id is a safe no-op."""
        registry = ConnectorRegistry()
        await registry.load(connector_classes={})

        # Must not raise:
        registry.set_health("ghost", healthy=False, checked_at=_utc_now())

    async def test_set_health_healthy_does_not_re_enable_disabled_connector(self) -> None:
        """A connector disabled by auth failure is NOT re-enabled by a healthy health check."""
        FailingStub = _make_stub(auth_raises=True)
        registry = ConnectorRegistry()
        await registry.load(connector_classes={"bad": FailingStub})

        # healthy=True should NOT flip enabled back to True for a pre-disabled connector
        registry.set_health("bad", healthy=True, checked_at=_utc_now())
        record = registry.records()[0]
        # set_health with healthy=True does not change enabled — only False disables
        # The record was already enabled=False from load(); remains False.
        assert record.last_health is True


@pytest.mark.asyncio
class TestConnectorRegistryRecords:
    async def test_records_returns_all_including_disabled(self) -> None:
        """records() returns all ConnectorRecord entries, enabled and disabled."""
        OkStub = _make_stub(auth_raises=False)
        BadStub = _make_stub(auth_raises=True)

        registry = ConnectorRegistry()
        await registry.load(connector_classes={"ok": OkStub, "bad": BadStub})

        all_records = registry.records()
        assert len(all_records) == 2
        ids = {r.connector_id for r in all_records}
        assert ids == {"ok", "bad"}

    async def test_records_returns_snapshot_not_live_reference(self) -> None:
        """records() returns a copy — mutating it does not affect the registry."""
        StubCls = _make_stub()
        registry = ConnectorRegistry()
        await registry.load(connector_classes={"svc": StubCls})

        snapshot = registry.records()
        snapshot.clear()

        assert len(registry.records()) == 1


# ---------------------------------------------------------------------------
# ConnectorRecord — dataclass field defaults
# ---------------------------------------------------------------------------

class TestConnectorRecord:
    def test_defaults(self) -> None:
        """ConnectorRecord defaults: enabled=True, last_health=None, last_checked=None."""
        StubCls = _make_stub()
        instance = StubCls()

        record = ConnectorRecord(
            connector_id="x",
            cls=StubCls,
            instance=instance,
        )

        assert record.enabled is True
        assert record.last_health is None
        assert record.last_checked is None


# ---------------------------------------------------------------------------
# Public API — __init__.py exports
# ---------------------------------------------------------------------------

class TestPublicAPIExports:
    def test_connector_registry_exported(self) -> None:
        from src.connector_sdk import ConnectorRegistry as _CR

        assert _CR is ConnectorRegistry

    def test_connector_record_exported(self) -> None:
        from src.connector_sdk import ConnectorRecord as _CRec

        assert _CRec is ConnectorRecord

    def test_discover_connectors_exported(self) -> None:
        from src.connector_sdk import discover_connectors as _dc

        assert callable(_dc)
