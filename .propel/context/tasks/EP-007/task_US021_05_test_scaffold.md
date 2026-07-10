# TASK-US021-05 — `BaseConnectorTestCase`: Unit Test Scaffold for Connector Developers

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US021-05 |
| User Story | US-021 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend / SDK |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Provide `BaseConnectorTestCase` — an abstract pytest class that connector developers subclass to get a ready-made suite of contract tests. Developers override two fixtures (`make_connector` and `sample_query`) and instantly validate that their connector satisfies the `BaseConnector` interface contract. Satisfies US-021 AC-6.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio

**File locations:**
- `src/connector_sdk/testing/base_test_case.py` — `BaseConnectorTestCase`
- `src/connector_sdk/testing/__init__.py` — re-export
- `tests/connector_sdk/test_echo_connector.py` — reference usage (tests `EchoConnector`)

**`BaseConnectorTestCase`:**

```python
# src/connector_sdk/testing/base_test_case.py
"""
Abstract pytest test class for BaseConnector implementations.

Usage:
    from src.connector_sdk.testing import BaseConnectorTestCase
    from my_connector import MyConnector

    class TestMyConnector(BaseConnectorTestCase):
        @pytest.fixture
        def make_connector(self):
            return MyConnector()

        @pytest.fixture
        def sample_query(self):
            return ConnectorQuery(query="test query", max_results=5)
"""
import pytest
from abc import abstractmethod
from datetime import datetime
from src.connector_sdk.base              import BaseConnector
from src.connector_sdk.schemas.query     import ConnectorQuery
from src.connector_sdk.schemas.result    import ConnectorResult
from src.connector_sdk.schemas.sync      import SyncResult
from src.connector_sdk.schemas.health    import HealthStatus


class BaseConnectorTestCase:
    """
    Subclass this and provide make_connector + sample_query fixtures.
    All tests are async; requires pytest-asyncio with asyncio_mode="auto".
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

    async def test_authenticate_does_not_raise(self, make_connector):
        """authenticate() must complete without raising."""
        await make_connector.authenticate()

    async def test_fetch_returns_list_of_connector_results(self, make_connector, sample_query):
        """fetch() must return a list[ConnectorResult]; may be empty."""
        await make_connector.authenticate()
        results = await make_connector.fetch(sample_query)
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, ConnectorResult)
            assert isinstance(r.fetched_at, datetime)
            assert r.source_id
            assert isinstance(r.content, str)

    async def test_sync_returns_sync_result(self, make_connector):
        """sync() must return a SyncResult with non-negative counts."""
        await make_connector.authenticate()
        result = await make_connector.sync()
        assert isinstance(result, SyncResult)
        assert result.items_processed >= 0
        assert result.items_failed    >= 0
        assert isinstance(result.last_sync_at, datetime)

    async def test_health_check_returns_health_status(self, make_connector):
        """health_check() must return HealthStatus and must not raise."""
        status = await make_connector.health_check()
        assert isinstance(status, HealthStatus)
        assert isinstance(status.healthy, bool)
        assert isinstance(status.message, str)
        assert len(status.message) <= 200
        assert isinstance(status.checked_at, datetime)

    async def test_health_check_does_not_raise_on_repeated_calls(self, make_connector):
        """health_check() must be safe to call repeatedly (poller calls every 30 s)."""
        for _ in range(3):
            status = await make_connector.health_check()
            assert isinstance(status, HealthStatus)

    async def test_fetch_respects_max_results(self, make_connector, sample_query):
        """fetch() must return at most max_results items."""
        await make_connector.authenticate()
        results = await make_connector.fetch(sample_query)
        assert len(results) <= sample_query.max_results
```

**Reference usage — `EchoConnector`:**

```python
# tests/connector_sdk/test_echo_connector.py
import pytest
from src.connector_sdk.testing    import BaseConnectorTestCase
from src.connector_sdk.schemas.query import ConnectorQuery
from examples.connectors.echo_connector.connector import EchoConnector

class TestEchoConnector(BaseConnectorTestCase):
    @pytest.fixture
    def make_connector(self):
        return EchoConnector()

    @pytest.fixture
    def sample_query(self):
        return ConnectorQuery(query="find hello world function", max_results=3)
```

**`pytest.ini` / `pyproject.toml` configuration:**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

Required for `async def test_*` methods in `BaseConnectorTestCase` to be discovered and run automatically.

**Connector developer workflow:**

1. `pip install contextiq-connector-sdk`
2. Subclass `BaseConnector`; implement 4 methods
3. Subclass `BaseConnectorTestCase`; provide `make_connector` fixture
4. Run `pytest` — all 6 contract tests must pass before submitting

## Acceptance Criteria

- [ ] `TestEchoConnector` (referencing `EchoConnector`) passes all 6 contract tests
- [ ] A connector that returns `None` from `fetch()` instead of `list[ConnectorResult]` fails `test_fetch_returns_list_of_connector_results`
- [ ] `BaseConnectorTestCase` cannot be instantiated and run directly (abstract fixtures prevent it)
- [ ] All 6 tests are `async def` and run under `pytest-asyncio` with `asyncio_mode="auto"`
- [ ] `src/connector_sdk/testing/__init__.py` exports `BaseConnectorTestCase` and `ConnectorQuery`

## Dependencies

- TASK-US021-01 (`BaseConnector`, `ConnectorQuery`, `ConnectorResult`, `SyncResult`, `HealthStatus`)
- TASK-US021-04 (`EchoConnector` — used as the reference implementation in `test_echo_connector.py`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `TestEchoConnector` runs in CI with no live I/O
- [ ] `mypy --strict` passes on `base_test_case.py`; no `ruff` lint errors
