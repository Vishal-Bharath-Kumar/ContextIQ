# TASK-US022-02 — `GitHubSearchClient`: Code Search API with Exponential Backoff

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US022-02 |
| User Story | US-022 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `GitHubSearchClient` — the HTTP client responsible for querying the GitHub Search API for code. It enforces a 2-second response time budget (US-022 AC-7), handles GitHub's 429 rate-limit responses with exponential backoff, and emits a Prometheus counter on every rate-limit hit (US-022 AC-6).

## Implementation Details

**Technology:** Python 3.11+, `httpx[asyncio]>=0.27`, `prometheus-client>=0.20`

**File locations:**
- `src/connectors/github/search_client.py` — `GitHubSearchClient`
- `src/connectors/github/metrics.py` — Prometheus metrics
- `tests/connectors/github/test_github_search_client.py`

**Prometheus metrics:**

```python
# src/connectors/github/metrics.py
from prometheus_client import Counter, Histogram

github_rate_limit_hits_total = Counter(
    "github_rate_limit_hits_total",
    "Number of GitHub API 429 rate-limit responses encountered",
    ["endpoint"],
)

github_search_latency_seconds = Histogram(
    "github_search_latency_seconds",
    "End-to-end latency of GitHub code search requests",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)
```

**`GitHubSearchItem` — raw API response row:**

```python
# src/connectors/github/search_client.py
from pydantic import BaseModel, ConfigDict

class GitHubFileItem(BaseModel):
    """One item from the GitHub Search API 'items' array."""
    model_config = ConfigDict(frozen=True)

    name:        str
    path:        str
    repository:  str          # "owner/repo"
    html_url:    str
    sha:         str          # blob SHA
    url:         str          # API URL for full content fetch
```

**`GitHubSearchClient`:**

```python
# src/connectors/github/search_client.py
import asyncio, time
import httpx
from src.connectors.github.metrics import github_rate_limit_hits_total, github_search_latency_seconds
from src.connectors.github.config  import GitHubConnectorConfig

_MAX_BACKOFF_S    = 60.0
_BACKOFF_BASE_S   = 1.0
_MAX_RETRIES      = 5

class GitHubSearchClient:
    def __init__(self, config: GitHubConnectorConfig) -> None:
        self._config = config

    async def search_code(
        self,
        query:        str,
        repos:        list[str],
        auth_header:  dict[str, str],
        max_results:  int = 50,
    ) -> list[GitHubFileItem]:
        """
        Query the GitHub Search API: GET /search/code
        Returns at most max_results items.
        Raises httpx.HTTPStatusError for non-retryable errors (4xx except 429).
        """
        repo_qualifier = " ".join(f"repo:{r}" for r in repos) if repos else ""
        q = f"{query} {repo_qualifier}".strip()
        params = {"q": q, "per_page": min(max_results, 100)}

        t0 = time.perf_counter()
        items = await self._get_with_backoff(
            url         = f"{self._config.base_url}/search/code",
            params      = params,
            auth_header = auth_header,
            endpoint    = "search_code",
        )
        elapsed = time.perf_counter() - t0
        github_search_latency_seconds.observe(elapsed)

        return [GitHubFileItem.model_validate(item) for item in items[:max_results]]

    async def _get_with_backoff(
        self,
        url:         str,
        params:      dict,
        auth_header: dict[str, str],
        endpoint:    str,
    ) -> list[dict]:
        headers = {**auth_header, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        attempt = 0
        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            while attempt < _MAX_RETRIES:
                response = await client.get(url, params=params, headers=headers)

                if response.status_code == 429:
                    github_rate_limit_hits_total.labels(endpoint=endpoint).inc()
                    retry_after = float(response.headers.get("Retry-After", _BACKOFF_BASE_S * (2 ** attempt)))
                    wait = min(retry_after, _MAX_BACKOFF_S)
                    await asyncio.sleep(wait)
                    attempt += 1
                    continue

                response.raise_for_status()
                return response.json().get("items", [])

        raise httpx.HTTPStatusError(
            f"GitHub API rate-limited after {_MAX_RETRIES} retries",
            request  = response.request,
            response = response,
        )
```

**2-second SLA (US-022 AC-7):**

The `GitHubConnectorConfig.request_timeout_s = 10.0` is the per-request HTTP timeout. The 2-second end-to-end SLA for `fetch()` (≤ 50 results) is enforced by wrapping the `search_code()` call in `asyncio.wait_for(..., timeout=2.0)` inside `GitHubConnector.fetch()` (TASK-US022-03). The search client itself does not enforce the budget to keep it testable in isolation.

**Backoff strategy:**

- `Retry-After` header value is respected if present (GitHub returns this on 429)
- Falls back to `1 × 2^attempt` seconds when `Retry-After` is absent
- Hard cap at 60 seconds per wait
- After `_MAX_RETRIES` exhausted, raises `HTTPStatusError` — the connector's `fetch()` propagates this

## Acceptance Criteria

- [ ] `search_code()` returns a list of `GitHubFileItem` models
- [ ] A 200 response with 30 items returns exactly 30 `GitHubFileItem` objects
- [ ] A 429 response triggers `github_rate_limit_hits_total.labels(endpoint="search_code").inc()`
- [ ] After `_MAX_RETRIES` consecutive 429s, `HTTPStatusError` is raised
- [ ] `Retry-After: 5` header results in a 5-second wait (mocked `asyncio.sleep`)
- [ ] `github_search_latency_seconds` histogram observes elapsed time after each successful call
- [ ] `max_results=30` returns at most 30 items even if the API returns more

## Dependencies

- TASK-US022-01 (`GitHubConnectorConfig`, `_auth_header()`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests use `httpx.MockTransport` or `respx`; no live GitHub API calls in CI
- [ ] `asyncio.sleep` patched in backoff tests to avoid real delays
- [ ] `mypy --strict` passes; no `ruff` lint errors
