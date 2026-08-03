# TASK-US023-05 — `ConfluenceConnector.health_check()` and Contract Test Suite

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US023-05 |
| User Story | US-023 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `ConfluenceConnector.health_check()` — a lightweight probe that validates the cached credential by calling the Confluence `/space` endpoint — and implement `TestConfluenceConnector`, the `BaseConnectorTestCase` subclass covering all 6 SDK contract tests plus Cloud/Data Center dual-path validation and a 2-second latency benchmark.

## Implementation Details

**Technology:** Python 3.11+, `httpx[asyncio]`, `respx`, `pytest`, `pytest-asyncio`, `pytest-benchmark`

**File locations:**
- `src/connectors/confluence/connector.py` — `ConfluenceConnector.health_check()` (extend existing class)
- `tests/connectors/confluence/test_confluence_contract.py` — `TestConfluenceConnector` + benchmark

**`ConfluenceConnector.health_check()`:**

```python
# src/connectors/confluence/connector.py  — extend existing class
import httpx
from datetime import datetime, timezone
from src.connector_sdk.schemas.health import HealthStatus
from src.connectors.confluence.config import ConfluenceDeploymentType

    async def health_check(self) -> HealthStatus:
        """
        Validate the cached token by calling GET /space (Cloud) or GET /rest/api/space (DC).
        Returns HealthStatus(healthy=False) on any error — must not raise.
        """
        now = datetime.now(tz=timezone.utc)
        try:
            if self._credential is None:
                return HealthStatus(
                    healthy    = False,
                    message    = "Not authenticated; call authenticate() first",
                    checked_at = now,
                )
            path  = (
                "/wiki/rest/api/space"
                if self._config.deployment_type == ConfluenceDeploymentType.CLOUD
                else "/rest/api/space"
            )
            url   = f"{self._config.base_url.rstrip('/')}{path}"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers=self._auth_headers(), params={"limit": 1})
            if resp.status_code == 200:
                return HealthStatus(
                    healthy    = True,
                    message    = f"Confluence reachable at {self._config.base_url}",
                    checked_at = now,
                )
            return HealthStatus(
                healthy    = False,
                message    = f"Confluence /space returned HTTP {resp.status_code}",
                checked_at = now,
            )
        except Exception as exc:
            return HealthStatus(
                healthy    = False,
                message    = f"{type(exc).__name__}: {str(exc)[:150]}",
                checked_at = now,
            )
```

**`TestConfluenceConnector` — contract tests:**

```python
# tests/connectors/confluence/test_confluence_contract.py
import pytest, respx, httpx, json
from unittest.mock import patch, AsyncMock
from src.connector_sdk.testing          import BaseConnectorTestCase
from src.connector_sdk.schemas.query    import ConnectorQuery
from src.connectors.confluence.connector import ConfluenceConnector
from src.connectors.confluence.config   import ConfluenceConnectorConfig, ConfluenceDeploymentType
from src.connectors.confluence.auth     import ConfluenceCredential

CLOUD_CONFIG = ConfluenceConnectorConfig(
    base_url         = "https://acme.atlassian.net",
    deployment_type  = ConfluenceDeploymentType.CLOUD,
    spaces           = ["ENG"],
    email            = "bot@acme.com",
    vault_role_id    = "test-role",
    vault_secret_id  = "test-secret",
)
DC_CONFIG = CLOUD_CONFIG.model_copy(update={
    "base_url":        "https://confluence.internal",
    "deployment_type": ConfluenceDeploymentType.DATACENTER,
    "email":           "",
})

MOCK_CLOUD_CREDENTIAL    = ConfluenceCredential(token="cloud-api-token",    deployment_type=ConfluenceDeploymentType.CLOUD,      email="bot@acme.com")
MOCK_DC_CREDENTIAL       = ConfluenceCredential(token="datacenter-pat",     deployment_type=ConfluenceDeploymentType.DATACENTER,  email="")

MOCK_SEARCH_RESPONSE = {
    "results": [{
        "id":    "123456",
        "title": "Auth Flow",
        "space": {"key": "ENG"},
        "_links": {"webui": "/spaces/ENG/pages/123456/Auth+Flow"},
        "body":  {"storage": {"value": "<p>Auth flow docs.</p>"}},
        "history": {
            "lastUpdated": {
                "when": "2026-06-01T10:00:00.000Z",
                "by":   {"displayName": "Alice"},
            }
        },
    }],
    "size": 1,
}

@pytest.fixture
def mock_vault_cloud():
    with patch(
        "src.connectors.confluence.connector.ConfluenceTokenProvider.get_credential",
        new_callable = AsyncMock,
        return_value = MOCK_CLOUD_CREDENTIAL,
    ):
        yield


class TestConfluenceConnector(BaseConnectorTestCase):

    @pytest.fixture
    def make_connector(self, mock_vault_cloud):
        return ConfluenceConnector(config=CLOUD_CONFIG)

    @pytest.fixture
    def sample_query(self):
        return ConnectorQuery(query="auth flow", max_results=5)

    @respx.mock
    async def test_fetch_returns_list_of_connector_results(self, make_connector, sample_query, mock_vault_cloud):
        await make_connector.authenticate()
        respx.get("https://acme.atlassian.net/wiki/rest/api/content/search").mock(
            return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
        )
        results = await make_connector.fetch(sample_query)
        assert results
        assert results[0].metadata.extra["space_key"] == "ENG"
        assert results[0].metadata.author             == "Alice"


class TestConfluenceConnectorDataCenter(BaseConnectorTestCase):
    """Validates Data Center deployment path — Bearer auth + different URL prefix."""

    @pytest.fixture
    def make_connector(self):
        with patch(
            "src.connectors.confluence.connector.ConfluenceTokenProvider.get_credential",
            new_callable = AsyncMock,
            return_value = MOCK_DC_CREDENTIAL,
        ):
            return ConfluenceConnector(config=DC_CONFIG)

    @pytest.fixture
    def sample_query(self):
        return ConnectorQuery(query="runbook", max_results=3)

    @respx.mock
    async def test_dc_uses_bearer_auth(self, make_connector, sample_query):
        await make_connector.authenticate()
        route = respx.get("https://confluence.internal/rest/api/content/search").mock(
            return_value=httpx.Response(200, json={"results": [], "size": 0})
        )
        await make_connector.fetch(sample_query)
        assert "Bearer" in route.calls.last.request.headers["authorization"]
```

**Latency benchmark:**

```python
    @respx.mock
    def test_fetch_under_2_seconds(self, benchmark, make_connector, mock_vault_cloud):
        import asyncio
        respx.get("https://acme.atlassian.net/wiki/rest/api/content/search").mock(
            return_value=httpx.Response(200, json={**MOCK_SEARCH_RESPONSE, "size": 50})
        )
        async def run():
            await make_connector.authenticate()
            return await make_connector.fetch(ConnectorQuery(query="*", max_results=50))
        result = benchmark(lambda: asyncio.run(run()))
        assert benchmark.stats["mean"] < 2.0
```

## Acceptance Criteria

- [ ] `health_check()` returns `HealthStatus(healthy=True)` when `/space` returns 200 (Cloud + DC paths)
- [ ] `health_check()` returns `HealthStatus(healthy=False)` when `/space` returns 401
- [ ] `health_check()` returns `HealthStatus(healthy=False)` when called before `authenticate()`
- [ ] `health_check()` does not raise when `httpx` raises a connection error
- [ ] All 6 `BaseConnectorTestCase` contract tests pass for `TestConfluenceConnector`
- [ ] `TestConfluenceConnectorDataCenter` verifies Bearer auth and DC URL path
- [ ] Fetch latency benchmark mean < 2 s (mocked responses)

## Dependencies

- TASK-US023-01 (`_auth_headers()`, `ConfluenceConnectorConfig`, both deployment types)
- TASK-US023-02 (`ConfluenceCQLClient` — mocked in contract tests)
- TASK-US023-03 (`ConfluenceConnector.fetch()` — exercised by contract tests)
- TASK-US021-05 (`BaseConnectorTestCase` — parent class)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Both Cloud and Data Center `health_check()` paths tested
- [ ] All tests use `respx`; no live Confluence calls in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
