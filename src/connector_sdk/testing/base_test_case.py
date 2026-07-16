"""
Abstract pytest test class for BaseConnector implementations.

Usage::

    from src.connector_sdk.testing import BaseConnectorTestCase
    from my_connector import MyConnector

    class TestMyConnector(BaseConnectorTestCase):
        @pytest.fixture
        def make_connector(self):
            return MyConnector()

        @pytest.fixture
        def sample_query(self):
            return ConnectorQuery(query="test query", max_results=5)

TASK-US021-05: BaseConnectorTestCase — Unit Test Scaffold for Connector Developers.
"""
from __future__ import annotations

from abc import abstractmethod
from datetime import datetime

import pytest

from src.connector_sdk.base import BaseConnector
from src.connector_sdk.schemas.health import HealthStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult
from src.connector_sdk.schemas.sync import SyncResult


class BaseConnectorTestCase:
    """
    Subclass this and provide ``make_connector`` + ``sample_query`` fixtures.

    All tests are ``async def``; requires pytest-asyncio with
    ``asyncio_mode = "auto"`` in ``pyproject.toml`` / ``pytest.ini``.
    """

    @pytest.fixture
    @abstractmethod
    def make_connector(self) -> BaseConnector:
        """Return a fully initialised connector instance ready for testing."""
        ...

    @pytest.fixture
    def sample_query(self) -> ConnectorQuery:
        """Return a ConnectorQuery suitable for the connector under test."""
        return ConnectorQuery(query="hello world", max_results=5)

    # ------------------------------------------------------------------
    # Contract tests
    # ------------------------------------------------------------------

    async def test_authenticate_does_not_raise(self, make_connector: BaseConnector) -> None:
        """authenticate() must complete without raising."""
        await make_connector.authenticate()

    async def test_fetch_returns_list_of_connector_results(
        self, make_connector: BaseConnector, sample_query: ConnectorQuery
    ) -> None:
        """fetch() must return a list[ConnectorResult]; may be empty."""
        await make_connector.authenticate()
        results = await make_connector.fetch(sample_query)
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, ConnectorResult)
            assert isinstance(r.fetched_at, datetime)
            assert r.source_id
            assert isinstance(r.content, str)

    async def test_sync_returns_sync_result(self, make_connector: BaseConnector) -> None:
        """sync() must return a SyncResult with non-negative counts."""
        await make_connector.authenticate()
        result = await make_connector.sync()
        assert isinstance(result, SyncResult)
        assert result.items_processed >= 0
        assert result.items_failed >= 0
        assert isinstance(result.last_sync_at, datetime)

    async def test_health_check_returns_health_status(
        self, make_connector: BaseConnector
    ) -> None:
        """health_check() must return HealthStatus and must not raise."""
        status = await make_connector.health_check()
        assert isinstance(status, HealthStatus)
        assert isinstance(status.healthy, bool)
        assert isinstance(status.message, str)
        assert len(status.message) <= 200
        assert isinstance(status.checked_at, datetime)

    async def test_health_check_does_not_raise_on_repeated_calls(
        self, make_connector: BaseConnector
    ) -> None:
        """health_check() must be safe to call repeatedly (poller calls every 30 s)."""
        for _ in range(3):
            status = await make_connector.health_check()
            assert isinstance(status, HealthStatus)

    async def test_fetch_respects_max_results(
        self, make_connector: BaseConnector, sample_query: ConnectorQuery
    ) -> None:
        """fetch() must return at most max_results items."""
        await make_connector.authenticate()
        results = await make_connector.fetch(sample_query)
        assert len(results) <= sample_query.max_results
