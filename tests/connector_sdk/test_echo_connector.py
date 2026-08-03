"""
Contract tests for EchoConnector using BaseConnectorTestCase.

TASK-US021-05: Reference usage of the test scaffold against the
EchoConnector example (TASK-US021-04).
"""
from __future__ import annotations

import pytest

from examples.connectors.echo_connector.connector import EchoConnector
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.testing import BaseConnectorTestCase


class TestEchoConnector(BaseConnectorTestCase):
    @pytest.fixture
    def make_connector(self) -> EchoConnector:
        return EchoConnector()

    @pytest.fixture
    def sample_query(self) -> ConnectorQuery:
        return ConnectorQuery(query="find hello world function", max_results=3)
