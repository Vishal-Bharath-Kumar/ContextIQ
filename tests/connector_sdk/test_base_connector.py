"""
Unit tests for TASK-US021-01: BaseConnector ABC and Core SDK Data Models.

Coverage targets:
  - BaseConnector cannot be instantiated directly (TypeError)
  - Concrete subclass that omits any abstract method raises TypeError
  - All four abstract methods are callable on a fully-implemented subclass
  - ConnectorQuery frozen — mutation raises ValidationError/TypeError
  - ConnectorQuery min_length=1 enforcement
  - ConnectorQuery max_results le=500 enforcement
  - ConnectorResult frozen
  - SyncResult frozen; errors defaults to empty list
  - HealthStatus frozen; unhealthy state is valid
  - HealthStatus message max_length=200 enforcement
  - ConnectorAuthError is a plain Exception subclass
  - Public API exported from src.connector_sdk.__init__
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)  # noqa: UP017


# ---------------------------------------------------------------------------
# Concrete stub used in multiple tests
# ---------------------------------------------------------------------------

class _StubConnector:
    """Fully-implemented stub — used to verify the happy path."""

    # Dynamically built as a real subclass inside each test that needs it
    # to avoid conftest-level import ordering issues.
    pass


def _make_full_stub() -> type:
    """Return a concrete BaseConnector subclass that implements all four methods."""
    from src.connector_sdk import (
        BaseConnector,
        ConnectorQuery,
        ConnectorResult,
        HealthStatus,
        SyncResult,
    )

    class _FullStub(BaseConnector):
        async def authenticate(self) -> None:
            return None

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

    return _FullStub


# ===========================================================================
# BaseConnector — ABC enforcement
# ===========================================================================

class TestBaseConnectorABC:
    def test_direct_instantiation_raises_type_error(self) -> None:
        """AC: Instantiating BaseConnector directly raises TypeError."""
        from src.connector_sdk import BaseConnector

        with pytest.raises(TypeError):
            BaseConnector()  # type: ignore[abstract]

    def test_missing_authenticate_raises_type_error(self) -> None:
        """AC: Subclass that omits authenticate() raises TypeError on instantiation."""
        from src.connector_sdk import (
            BaseConnector,
            ConnectorQuery,
            ConnectorResult,
            HealthStatus,
            SyncResult,
        )

        class _MissingAuth(BaseConnector):
            async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
                return []

            async def sync(self) -> SyncResult:
                return SyncResult(items_processed=0, items_failed=0, last_sync_at=_utc_now())

            async def health_check(self) -> HealthStatus:
                return HealthStatus(healthy=True, message="ok", checked_at=_utc_now())

        with pytest.raises(TypeError):
            _MissingAuth()  # type: ignore[abstract]

    def test_missing_fetch_raises_type_error(self) -> None:
        from src.connector_sdk import BaseConnector, HealthStatus, SyncResult

        class _MissingFetch(BaseConnector):
            async def authenticate(self) -> None:
                pass

            async def sync(self) -> SyncResult:
                return SyncResult(items_processed=0, items_failed=0, last_sync_at=_utc_now())

            async def health_check(self) -> HealthStatus:
                return HealthStatus(healthy=True, message="ok", checked_at=_utc_now())

        with pytest.raises(TypeError):
            _MissingFetch()  # type: ignore[abstract]

    def test_missing_sync_raises_type_error(self) -> None:
        from src.connector_sdk import (
            BaseConnector,
            ConnectorQuery,
            ConnectorResult,
            HealthStatus,
        )

        class _MissingSync(BaseConnector):
            async def authenticate(self) -> None:
                pass

            async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
                return []

            async def health_check(self) -> HealthStatus:
                return HealthStatus(healthy=True, message="ok", checked_at=_utc_now())

        with pytest.raises(TypeError):
            _MissingSync()  # type: ignore[abstract]

    def test_missing_health_check_raises_type_error(self) -> None:
        from src.connector_sdk import (
            BaseConnector,
            ConnectorQuery,
            ConnectorResult,
            SyncResult,
        )

        class _MissingHealth(BaseConnector):
            async def authenticate(self) -> None:
                pass

            async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
                return []

            async def sync(self) -> SyncResult:
                return SyncResult(items_processed=0, items_failed=0, last_sync_at=_utc_now())

        with pytest.raises(TypeError):
            _MissingHealth()  # type: ignore[abstract]

    def test_full_implementation_instantiates_successfully(self) -> None:
        """AC: A class implementing all four methods can be instantiated."""
        stub_cls = _make_full_stub()
        instance = stub_cls()
        assert isinstance(instance, stub_cls)


# ===========================================================================
# BaseConnector — abstract methods are callable on full stub
# ===========================================================================

class TestBaseConnectorMethods:
    @pytest.mark.asyncio
    async def test_authenticate_callable(self) -> None:
        instance = _make_full_stub()()
        result = await instance.authenticate()
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_returns_list(self) -> None:
        from src.connector_sdk import ConnectorQuery

        instance = _make_full_stub()()
        results = await instance.fetch(ConnectorQuery(query="hello"))
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_sync_returns_sync_result(self) -> None:
        from src.connector_sdk import SyncResult

        instance = _make_full_stub()()
        result = await instance.sync()
        assert isinstance(result, SyncResult)

    @pytest.mark.asyncio
    async def test_health_check_returns_health_status(self) -> None:
        from src.connector_sdk import HealthStatus

        instance = _make_full_stub()()
        status = await instance.health_check()
        assert isinstance(status, HealthStatus)
        assert status.healthy is True


# ===========================================================================
# ConnectorQuery — validation
# ===========================================================================

class TestConnectorQuery:
    def test_valid_defaults(self) -> None:
        from src.connector_sdk import ConnectorQuery

        q = ConnectorQuery(query="find me something")
        assert q.max_results == 50
        assert q.filters == {}

    def test_empty_query_raises_validation_error(self) -> None:
        """AC: ConnectorQuery(query='') raises ValidationError (min_length=1)."""
        from pydantic import ValidationError

        from src.connector_sdk import ConnectorQuery

        with pytest.raises(ValidationError):
            ConnectorQuery(query="")

    def test_max_results_over_500_raises_validation_error(self) -> None:
        """AC: ConnectorQuery(max_results=501) raises ValidationError (le=500)."""
        from pydantic import ValidationError

        from src.connector_sdk import ConnectorQuery

        with pytest.raises(ValidationError):
            ConnectorQuery(query="test", max_results=501)

    def test_max_results_zero_raises_validation_error(self) -> None:
        """max_results must be > 0."""
        from pydantic import ValidationError

        from src.connector_sdk import ConnectorQuery

        with pytest.raises(ValidationError):
            ConnectorQuery(query="test", max_results=0)

    def test_max_results_boundary_500_is_valid(self) -> None:
        from src.connector_sdk import ConnectorQuery

        q = ConnectorQuery(query="test", max_results=500)
        assert q.max_results == 500

    def test_query_max_length_2000(self) -> None:
        from pydantic import ValidationError

        from src.connector_sdk import ConnectorQuery

        with pytest.raises(ValidationError):
            ConnectorQuery(query="x" * 2001)

    def test_frozen_mutation_raises(self) -> None:
        """AC: All schema models are frozen — mutation raises ValidationError."""
        from pydantic import ValidationError

        from src.connector_sdk import ConnectorQuery

        q = ConnectorQuery(query="test")
        with pytest.raises(ValidationError):
            q.query = "changed"  # type: ignore[misc]

    def test_custom_filters(self) -> None:
        from src.connector_sdk import ConnectorQuery

        q = ConnectorQuery(query="test", filters={"lang": "python", "repo": "contextiq"})
        assert q.filters["lang"] == "python"


# ===========================================================================
# ConnectorResult — validation and frozen
# ===========================================================================

class TestConnectorResult:
    def test_valid_construction(self) -> None:
        from src.connector_sdk import ConnectorResult, ResultMetadata

        result = ConnectorResult(
            source_id="doc-001",
            content="some text",
            metadata=ResultMetadata(),
            fetched_at=_utc_now(),
        )
        assert result.source_id == "doc-001"

    def test_frozen_mutation_raises(self) -> None:
        from pydantic import ValidationError

        from src.connector_sdk import ConnectorResult, ResultMetadata

        result = ConnectorResult(
            source_id="doc-001",
            content="text",
            metadata=ResultMetadata(),
            fetched_at=_utc_now(),
        )
        with pytest.raises(ValidationError):
            result.content = "changed"  # type: ignore[misc]

    def test_result_metadata_defaults(self) -> None:
        from src.connector_sdk import ResultMetadata

        meta = ResultMetadata()
        assert meta.source_url is None
        assert meta.author is None
        assert meta.last_modified is None
        assert meta.extra == {}

    def test_result_metadata_frozen(self) -> None:
        from pydantic import ValidationError

        from src.connector_sdk import ResultMetadata

        meta = ResultMetadata(author="alice")
        with pytest.raises(ValidationError):
            meta.author = "bob"  # type: ignore[misc]


# ===========================================================================
# SyncResult — validation and frozen
# ===========================================================================

class TestSyncResult:
    def test_errors_defaults_to_empty_list(self) -> None:
        """AC: SyncResult.errors defaults to []."""
        from src.connector_sdk import SyncResult

        result = SyncResult(items_processed=5, items_failed=0, last_sync_at=_utc_now())
        assert result.errors == []

    def test_errors_can_be_populated(self) -> None:
        from src.connector_sdk import SyncResult

        result = SyncResult(
            items_processed=3,
            items_failed=1,
            last_sync_at=_utc_now(),
            errors=["item-007: timeout"],
        )
        assert len(result.errors) == 1

    def test_frozen_mutation_raises(self) -> None:
        """AC: SyncResult is frozen."""
        from pydantic import ValidationError

        from src.connector_sdk import SyncResult

        result = SyncResult(items_processed=0, items_failed=0, last_sync_at=_utc_now())
        with pytest.raises(ValidationError):
            result.items_processed = 99  # type: ignore[misc]


# ===========================================================================
# HealthStatus — validation and frozen
# ===========================================================================

class TestHealthStatus:
    def test_healthy_true_constructs(self) -> None:
        from src.connector_sdk import HealthStatus

        status = HealthStatus(healthy=True, message="all good", checked_at=_utc_now())
        assert status.healthy is True

    def test_healthy_false_constructs(self) -> None:
        """AC: HealthStatus(healthy=False, ...) constructs without error."""
        from src.connector_sdk import HealthStatus

        status = HealthStatus(healthy=False, message="db unreachable", checked_at=_utc_now())
        assert status.healthy is False

    def test_message_max_length_200(self) -> None:
        from pydantic import ValidationError

        from src.connector_sdk import HealthStatus

        with pytest.raises(ValidationError):
            HealthStatus(healthy=True, message="x" * 201, checked_at=_utc_now())

    def test_message_exactly_200_chars_is_valid(self) -> None:
        from src.connector_sdk import HealthStatus

        status = HealthStatus(healthy=True, message="x" * 200, checked_at=_utc_now())
        assert len(status.message) == 200

    def test_frozen_mutation_raises(self) -> None:
        from pydantic import ValidationError

        from src.connector_sdk import HealthStatus

        status = HealthStatus(healthy=True, message="ok", checked_at=_utc_now())
        with pytest.raises(ValidationError):
            status.healthy = False  # type: ignore[misc]


# ===========================================================================
# ConnectorAuthError
# ===========================================================================

class TestConnectorAuthError:
    def test_is_exception_subclass(self) -> None:
        from src.connector_sdk import ConnectorAuthError

        assert issubclass(ConnectorAuthError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        from src.connector_sdk import ConnectorAuthError

        with pytest.raises(ConnectorAuthError, match="token expired"):
            raise ConnectorAuthError("token expired")


# ===========================================================================
# Public API surface — __init__ exports
# ===========================================================================

class TestPublicAPI:
    def test_all_types_importable_from_top_level(self) -> None:
        import src.connector_sdk as sdk

        assert hasattr(sdk, "BaseConnector")
        assert hasattr(sdk, "ConnectorAuthError")
        assert hasattr(sdk, "ConnectorQuery")
        assert hasattr(sdk, "ConnectorResult")
        assert hasattr(sdk, "ResultMetadata")
        assert hasattr(sdk, "SyncResult")
        assert hasattr(sdk, "HealthStatus")

    def test_all_names_in_dunder_all(self) -> None:
        import src.connector_sdk as sdk

        for name in [
            "BaseConnector",
            "ConnectorAuthError",
            "ConnectorQuery",
            "ConnectorResult",
            "ResultMetadata",
            "SyncResult",
            "HealthStatus",
        ]:
            assert name in sdk.__all__, f"{name!r} missing from __all__"
