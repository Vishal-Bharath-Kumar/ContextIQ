# TASK-US024-05 — Contract Tests for `JiraConnector` and `GrafanaConnector`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US024-05 |
| User Story | US-024 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `TestJiraConnector` and `TestGrafanaConnector` — `BaseConnectorTestCase` subclasses that run all 6 SDK contract tests against mocked HTTP responses for both connectors. Includes independent enable/disable toggle tests (US-024 AC-5) and 3-second latency benchmarks for both `fetch()` implementations (US-024 AC-6).

## Implementation Details

**Technology:** Python 3.11+, `respx`, `pytest`, `pytest-asyncio`, `pytest-benchmark`

**File locations:**
- `tests/connectors/jira/test_jira_contract.py` — `TestJiraConnector`
- `tests/connectors/grafana/test_grafana_contract.py` — `TestGrafanaConnector`

**`TestJiraConnector`:**

```python
# tests/connectors/jira/test_jira_contract.py
import pytest, respx, httpx
from unittest.mock import patch, AsyncMock
from src.connector_sdk.testing         import BaseConnectorTestCase
from src.connector_sdk.schemas.query   import ConnectorQuery
from src.connectors.jira.connector     import JiraConnector
from src.connectors.jira.config        import JiraConnectorConfig
from src.connectors.jira.auth          import JiraCredential

JIRA_CONFIG = JiraConnectorConfig(
    enabled        = True,
    base_url       = "https://acme.atlassian.net",
    email          = "bot@acme.com",
    projects       = ["OPS"],
    vault_role_id  = "test-role",
    vault_secret_id = "test-secret",
)
MOCK_JIRA_CREDENTIAL = JiraCredential(token="test-jira-token", email="bot@acme.com")

MOCK_SEARCH_RESPONSE = {
    "issues": [{
        "key": "OPS-42",
        "fields": {
            "summary":     "Database connection pool exhausted",
            "status":      {"name": "In Progress"},
            "priority":    {"name": "High"},
            "assignee":    {"displayName": "Bob"},
            "description": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Pool size exceeded."}]}]
            },
            "updated": "2026-07-09T08:00:00.000+0000",
        }
    }]
}

@pytest.fixture
def mock_jira_vault():
    with patch(
        "src.connectors.jira.connector.JiraTokenProvider.get_credential",
        new_callable = AsyncMock,
        return_value = MOCK_JIRA_CREDENTIAL,
    ):
        yield


class TestJiraConnector(BaseConnectorTestCase):

    @pytest.fixture
    def make_connector(self, mock_jira_vault):
        return JiraConnector(config=JIRA_CONFIG)

    @pytest.fixture
    def sample_query(self):
        return ConnectorQuery(query="database connection", max_results=5)

    @respx.mock
    async def test_fetch_returns_list_of_connector_results(self, make_connector, sample_query, mock_jira_vault):
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/rest/api/3/search").mock(
            return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
        )
        results = await make_connector.fetch(sample_query)
        assert results
        assert results[0].source_id                == "jira:OPS-42"
        assert results[0].metadata.extra["status"] == "In Progress"
        assert results[0].metadata.extra["priority"] == "High"
        assert results[0].metadata.author           == "Bob"


# AC-5: independently disable Jira without affecting Grafana
async def test_jira_disabled_raises_auth_error(mock_jira_vault):
    from src.connector_sdk.exceptions import ConnectorAuthError
    disabled_config = JIRA_CONFIG.model_copy(update={"enabled": False})
    connector = JiraConnector(config=disabled_config)
    with pytest.raises(ConnectorAuthError, match="disabled"):
        await connector.authenticate()


@respx.mock
def test_jira_fetch_under_3_seconds(benchmark, mock_jira_vault):
    """Verify fetch() completes within 3 s for ≤ 50 results (mocked)."""
    import asyncio
    respx.get("https://acme.atlassian.net/rest/api/3/search").mock(
        return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
    )
    async def run():
        connector = JiraConnector(config=JIRA_CONFIG)
        await connector.authenticate()
        return await connector.fetch(ConnectorQuery(query="ops", max_results=50))
    benchmark(lambda: asyncio.run(run()))
    assert benchmark.stats["mean"] < 3.0
```

**`TestGrafanaConnector`:**

```python
# tests/connectors/grafana/test_grafana_contract.py
import pytest, respx, httpx
from unittest.mock import patch, AsyncMock
from src.connector_sdk.testing          import BaseConnectorTestCase
from src.connector_sdk.schemas.query    import ConnectorQuery
from src.connectors.grafana.connector   import GrafanaConnector
from src.connectors.grafana.config      import GrafanaConnectorConfig
from src.connectors.grafana.auth        import GrafanaCredential

GRAFANA_CONFIG = GrafanaConnectorConfig(
    enabled         = True,
    base_url        = "https://grafana.internal",
    lookback_hours  = 24,
    vault_role_id   = "test-role",
    vault_secret_id = "test-secret",
)
MOCK_GRAFANA_CREDENTIAL = GrafanaCredential(token="glsa_test_service_token")

MOCK_ANNOTATIONS = [{"id": 1, "text": "Deploy spike", "newState": "alerting",
                      "time": 1720000000000, "dashboardUID": "abc"}]
MOCK_ALERTS      = [{"fingerprint": "f1", "labels": {"alertname": "HighCPU"},
                      "status": {"state": "firing"}, "annotations": {"message": "CPU > 90%"},
                      "startsAt": "2026-07-09T07:00:00Z"}]

@pytest.fixture
def mock_grafana_vault():
    with patch(
        "src.connectors.grafana.connector.GrafanaTokenProvider.get_credential",
        new_callable = AsyncMock,
        return_value = MOCK_GRAFANA_CREDENTIAL,
    ):
        yield


class TestGrafanaConnector(BaseConnectorTestCase):

    @pytest.fixture
    def make_connector(self, mock_grafana_vault):
        return GrafanaConnector(config=GRAFANA_CONFIG)

    @pytest.fixture
    def sample_query(self):
        return ConnectorQuery(query="CPU", max_results=10)

    @respx.mock
    async def test_fetch_returns_list_of_connector_results(self, make_connector, sample_query, mock_grafana_vault):
        await make_connector.authenticate()
        respx.get("https://grafana.internal/api/annotations").mock(
            return_value=httpx.Response(200, json=MOCK_ANNOTATIONS)
        )
        respx.get("https://grafana.internal/api/alertmanager/grafana/api/v2/alerts").mock(
            return_value=httpx.Response(200, json=MOCK_ALERTS)
        )
        results = await make_connector.fetch(sample_query)
        assert any(r.source_id == "grafana:annotation:1" for r in results)
        assert any(r.source_id == "grafana:alert:f1" for r in results)


# AC-5: independently disable Grafana
async def test_grafana_disabled_raises_auth_error(mock_grafana_vault):
    from src.connector_sdk.exceptions import ConnectorAuthError
    disabled = GRAFANA_CONFIG.model_copy(update={"enabled": False})
    connector = GrafanaConnector(config=disabled)
    with pytest.raises(ConnectorAuthError, match="disabled"):
        await connector.authenticate()


# Alert degradation: Alertmanager 404 → annotations still returned
@respx.mock
async def test_grafana_fetch_degrades_on_alertmanager_failure(mock_grafana_vault):
    connector = GrafanaConnector(config=GRAFANA_CONFIG)
    await connector.authenticate()
    respx.get("https://grafana.internal/api/annotations").mock(
        return_value=httpx.Response(200, json=MOCK_ANNOTATIONS)
    )
    respx.get("https://grafana.internal/api/alertmanager/grafana/api/v2/alerts").mock(
        return_value=httpx.Response(404)
    )
    results = await connector.fetch(ConnectorQuery(query="", max_results=50))
    assert any(r.source_id == "grafana:annotation:1" for r in results)
    # No alert results — but no exception raised
    assert all(r.metadata.extra["type"] == "annotation" for r in results)
```

## Acceptance Criteria

- [ ] All 6 `BaseConnectorTestCase` contract tests pass for `TestJiraConnector`
- [ ] All 6 `BaseConnectorTestCase` contract tests pass for `TestGrafanaConnector`
- [ ] `test_jira_disabled_raises_auth_error` confirms `enabled=False` raises `ConnectorAuthError`
- [ ] `test_grafana_disabled_raises_auth_error` confirms `enabled=False` raises `ConnectorAuthError`
- [ ] `test_grafana_fetch_degrades_on_alertmanager_failure` verifies partial results on Alertmanager 404
- [ ] Jira benchmark mean < 3 s; Grafana benchmark mean < 3 s (mocked responses)
- [ ] Both connectors' tests are independent — no shared state between test classes

## Dependencies

- TASK-US024-01 (connector skeletons, `_auth_headers()`, enable/disable logic)
- TASK-US024-02 (`JiraConnector.fetch()`, `health_check()`)
- TASK-US024-03 (`GrafanaConnector.fetch()`, `health_check()`)
- TASK-US021-05 (`BaseConnectorTestCase` — parent class)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests use `respx`; no live Jira or Grafana calls in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
