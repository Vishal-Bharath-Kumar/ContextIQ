# TASK-US022-05 — `GitHubConnector.health_check()` and Contract Test Suite

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US022-05 |
| User Story | US-022 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `GitHubConnector.health_check()` — a lightweight probe that validates the cached token by calling the GitHub `/rate_limit` endpoint. Also implement `TestGitHubConnector` — the `BaseConnectorTestCase` subclass that runs all 6 SDK contract tests against a mocked GitHub connector, plus a `pytest-benchmark` performance test validating the 2-second latency SLA for ≤ 50 results.

## Implementation Details

**Technology:** Python 3.11+, `httpx[asyncio]`, `pytest`, `pytest-asyncio`, `pytest-benchmark`, `respx`

**File locations:**
- `src/connectors/github/connector.py` — `GitHubConnector.health_check()` (extend existing class)
- `tests/connectors/github/test_github_contract.py` — `TestGitHubConnector` + benchmark

**`GitHubConnector.health_check()`:**

```python
# src/connectors/github/connector.py  — extend existing class
import httpx
from datetime import datetime, timezone
from src.connector_sdk.schemas.health import HealthStatus

    async def health_check(self) -> HealthStatus:
        """
        Validate the cached token by calling GET /rate_limit.
        Must not raise — all exceptions are caught and reported as unhealthy.
        """
        now = datetime.now(tz=timezone.utc)
        try:
            if self._credential is None:
                return HealthStatus(
                    healthy    = False,
                    message    = "Not authenticated; call authenticate() first",
                    checked_at = now,
                )
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._config.base_url}/rate_limit",
                    headers = {
                        **self._auth_header(),
                        "Accept":               "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
            if resp.status_code == 200:
                remaining = resp.json().get("rate", {}).get("remaining", -1)
                return HealthStatus(
                    healthy    = True,
                    message    = f"GitHub API reachable; rate_limit.remaining={remaining}",
                    checked_at = now,
                )
            return HealthStatus(
                healthy    = False,
                message    = f"GitHub /rate_limit returned HTTP {resp.status_code}",
                checked_at = now,
            )
        except Exception as exc:
            return HealthStatus(
                healthy    = False,
                message    = f"{type(exc).__name__}: {str(exc)[:150]}",
                checked_at = now,
            )
```

**`TestGitHubConnector` — contract tests:**

```python
# tests/connectors/github/test_github_contract.py
import pytest, respx, httpx, json
from datetime import datetime, timezone
from src.connector_sdk.testing        import BaseConnectorTestCase
from src.connector_sdk.schemas.query  import ConnectorQuery
from src.connectors.github.connector  import GitHubConnector
from src.connectors.github.config     import GitHubConnectorConfig
from unittest.mock import patch, AsyncMock

MOCK_CONFIG = GitHubConnectorConfig(
    repos         = ["acme/backend"],
    vault_path    = "secret/data/github/token",
    vault_role_id = "test-role",
    vault_secret_id = "test-secret",
)

@pytest.fixture
def mock_vault_credential():
    """Patch GitHubTokenProvider to return a fixture credential."""
    from src.connectors.github.auth import GitHubCredential
    with patch(
        "src.connectors.github.connector.GitHubTokenProvider.get_credential",
        new_callable = AsyncMock,
        return_value = GitHubCredential(token="ghp_testtoken", token_type="pat"),
    ):
        yield


class TestGitHubConnector(BaseConnectorTestCase):

    @pytest.fixture
    def make_connector(self, mock_vault_credential):
        return GitHubConnector(config=MOCK_CONFIG)

    @pytest.fixture
    def sample_query(self):
        return ConnectorQuery(query="def authenticate", max_results=5)

    # Override fetch test to mock HTTP responses
    @respx.mock
    async def test_fetch_returns_list_of_connector_results(self, make_connector, sample_query, mock_vault_credential):
        await make_connector.authenticate()

        # Mock search API
        respx.get("https://api.github.com/search/code").mock(return_value=httpx.Response(
            200,
            json={"items": [{"name": "connector.py", "path": "src/connector.py",
                              "repository": {"full_name": "acme/backend"},
                              "html_url": "https://github.com/acme/backend/blob/main/src/connector.py",
                              "sha": "abc123", "url": "https://api.github.com/repos/acme/backend/contents/src/connector.py"}]},
        ))
        # Mock content API
        respx.get("https://api.github.com/repos/acme/backend/contents/src/connector.py").mock(
            return_value=httpx.Response(200, text="def authenticate(): pass")
        )
        # Mock commits API
        respx.get("https://api.github.com/repos/acme/backend/commits").mock(return_value=httpx.Response(
            200,
            json=[{"sha": "abc123", "commit": {"committer": {"date": "2026-07-01T10:00:00Z"}}}]
        ))

        results = await make_connector.fetch(sample_query)
        assert results
        assert results[0].metadata.extra["repository"] == "acme/backend"
        assert results[0].metadata.extra["commit_sha"] == "abc123"
```

**Performance test — 2-second SLA:**

```python
    @respx.mock
    def test_fetch_under_2_seconds(self, benchmark, make_connector, mock_vault_credential):
        """Verify fetch() completes within 2 s for ≤ 50 results (mocked responses)."""
        import asyncio

        # ... configure respx mocks for 50 results ...

        async def run():
            await make_connector.authenticate()
            return await make_connector.fetch(ConnectorQuery(query="def", max_results=50))

        result = benchmark(lambda: asyncio.run(run()))
        assert benchmark.stats["mean"] < 2.0, (
            f"fetch() mean latency {benchmark.stats['mean']:.2f}s exceeded 2 s SLA"
        )
```

## Acceptance Criteria

- [ ] `health_check()` returns `HealthStatus(healthy=True)` when `/rate_limit` returns 200
- [ ] `health_check()` returns `HealthStatus(healthy=False)` when `/rate_limit` returns 401
- [ ] `health_check()` returns `HealthStatus(healthy=False)` when called before `authenticate()`
- [ ] `health_check()` does not raise when `httpx` raises a connection error
- [ ] All 6 `BaseConnectorTestCase` contract tests pass for `TestGitHubConnector`
- [ ] `test_fetch_under_2_seconds` mean latency is < 2 s (mocked responses)

## Dependencies

- TASK-US022-01 (`_auth_header()`, `GitHubConnectorConfig`)
- TASK-US022-02 (`GitHubSearchClient` — mocked in contract tests)
- TASK-US022-03 (`GitHubConnector.fetch()` — exercised by contract tests)
- TASK-US021-05 (`BaseConnectorTestCase` — parent class)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests use `respx` mocks; no live GitHub API in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
