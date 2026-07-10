# TASK-US032-02 — `OPAClient` and `PolicyBundleLoader`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US032-02 |
| User Story | US-032 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `OPAClient` — the async component that calls the OPA sidecar's REST API at `POST /v1/data/contextiq/authz/allow` for each context chunk and returns a `PolicyDecision`. Implement `PolicyBundleLoader` — the startup component that verifies the OPA sidecar has loaded the correct versioned bundle and records `BundleInfo`. Satisfies AC-1 (bundle loaded at startup), AC-2 (OPA call per chunk with required fields), AC-5 (≤ 50 ms per chunk via localhost).

## Implementation Details

**Technology:** Python 3.11+, `httpx[asyncio]>=0.27`, Pydantic v2, `pydantic-settings`

**File locations:**
- `src/governance/opa/client.py` — `OPAClient`, `OPAClientSettings`
- `src/governance/opa/bundle_loader.py` — `PolicyBundleLoader`
- `tests/governance/test_opa_client.py`

---

### OPA deployment model

OPA runs as a sidecar container in the same pod as the ContextIQ gateway. Calls to `http://localhost:8181` are IPC-level, not network round-trips, achieving < 1 ms transport overhead. The "inline evaluation, not remote call" in AC-5 refers to this co-located deployment — not to in-process Rego compilation.

The OPA sidecar is configured with a bundle config pointing to the versioned policy repository (S3, GCS, or an HTTP policy server). On startup, OPA fetches the bundle; `PolicyBundleLoader.verify()` confirms the bundle is active before the gateway begins serving requests.

---

### `OPAClientSettings`

```python
# src/governance/opa/client.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class OPAClientSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPA_", env_file=".env")

    base_url:             str   = "http://localhost:8181"
    # Per-chunk call timeout. Must be < 50 ms (AC-5) with headroom for hot path.
    request_timeout_s:    float = 0.05
    # OPA data path for the policy rule (AC-2).
    policy_path:          str   = "v1/data/contextiq/authz/allow"
    # OPA status endpoint for bundle verification (AC-1).
    status_path:          str   = "v1/status"
    # Expected bundle name as configured in the OPA sidecar bundle config.
    expected_bundle_name: str   = "contextiq_policies"
    # Connection pool size — reuse connections across concurrent evaluations.
    max_connections:      int   = 20
```

---

### `OPAClient`

```python
# src/governance/opa/client.py (continued)
import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from src.governance.opa.schemas import ChunkAuthzInput, PolicyDecision, AuthzFilterResult

logger = logging.getLogger(__name__)


class OPAEvaluationError(RuntimeError):
    """Raised when OPA returns a non-200 response or the call times out."""


class OPAClient:
    def __init__(self, settings: OPAClientSettings | None = None) -> None:
        self._settings = settings or OPAClientSettings()
        # Single shared async client — connection pool is reused across evaluations.
        self._http = httpx.AsyncClient(
            base_url = self._settings.base_url,
            timeout  = self._settings.request_timeout_s,
            limits   = httpx.Limits(max_connections=self._settings.max_connections),
        )

    async def evaluate_chunk(self, inp: ChunkAuthzInput) -> PolicyDecision:
        """
        Call OPA `data.contextiq.authz.allow` for a single chunk.

        OPA REST API request format:
          POST /v1/data/contextiq/authz/allow
          {"input": <ChunkAuthzInput as dict>}

        Response: {"result": true|false}

        The Rego `deny_reason` rule is fetched as a second call only when
        allow=False, to avoid the overhead on the allow (common) path.

        Raises OPAEvaluationError on HTTP error or timeout.
        """
        start   = time.monotonic()
        payload = {"input": inp.model_dump()}
        url     = self._settings.policy_path

        try:
            response = await self._http.post(url, json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OPAEvaluationError(
                f"OPA evaluation timed out for chunk={inp.chunk_id}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OPAEvaluationError(
                f"OPA returned HTTP {exc.response.status_code} for chunk={inp.chunk_id}"
            ) from exc

        data    = response.json()
        allowed = bool(data.get("result", False))
        eval_ms = (time.monotonic() - start) * 1000

        rationale = ""
        if not allowed:
            rationale = await self._fetch_deny_reason(inp)

        return PolicyDecision(
            chunk_id  = inp.chunk_id,
            allow     = allowed,
            rationale = rationale,
            eval_ms   = eval_ms,
        )

    async def evaluate_batch(
        self,
        inputs:      list[ChunkAuthzInput],
        concurrency: int = 10,
    ) -> AuthzFilterResult:
        """
        Evaluate all chunks concurrently (bounded by `concurrency` semaphore).
        Returns AuthzFilterResult with allow/deny split and total eval time.

        Concurrency=10 at 50 ms each → effective throughput ≥ 200 chunks/s,
        well above the typical context window size of 20–50 chunks.
        """
        sem   = asyncio.Semaphore(concurrency)
        start = time.monotonic()

        async def _eval_one(inp: ChunkAuthzInput) -> PolicyDecision:
            async with sem:
                return await self.evaluate_chunk(inp)

        decisions     = await asyncio.gather(*[_eval_one(i) for i in inputs])
        total_eval_ms = (time.monotonic() - start) * 1000

        allowed = [d.chunk_id for d in decisions if d.allow]
        denied  = [d.chunk_id for d in decisions if d.is_denied]

        return AuthzFilterResult(
            decisions         = list(decisions),
            allowed_chunk_ids = allowed,
            denied_chunk_ids  = denied,
            total_eval_ms     = total_eval_ms,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _fetch_deny_reason(self, inp: ChunkAuthzInput) -> str:
        """
        Fetch the Rego `deny_reason` rule value for a denied chunk.
        Returns empty string on any error — denial is already recorded.
        """
        url = "v1/data/contextiq/authz/deny_reason"
        try:
            resp = await self._http.post(url, json={"input": inp.model_dump()})
            resp.raise_for_status()
            return str(resp.json().get("result") or "")
        except Exception:
            return ""
```

---

### `PolicyBundleLoader`

```python
# src/governance/opa/bundle_loader.py
import logging
from datetime import datetime, timezone
import httpx
from src.governance.opa.client  import OPAClientSettings
from src.governance.opa.schemas import BundleInfo

logger = logging.getLogger(__name__)


class BundleNotReadyError(RuntimeError):
    """Raised at startup if the expected OPA bundle is not yet active."""


class PolicyBundleLoader:
    """
    Verifies the OPA sidecar has loaded the configured policy bundle at startup
    and returns a BundleInfo for logging and hot-reload tracking.

    OPA exposes bundle activation status via GET /v1/status:
      {
        "bundles": {
          "contextiq_policies": {
            "active_revision": "v1.2.3",
            ...
          }
        }
      }
    """

    def __init__(self, settings: OPAClientSettings | None = None) -> None:
        self._settings = settings or OPAClientSettings()

    async def verify(self) -> BundleInfo:
        """
        Poll the OPA status endpoint until the expected bundle is active,
        or raise BundleNotReadyError after max_attempts.

        Called once during application lifespan startup — before the gateway
        begins accepting requests (AC-1).
        """
        import asyncio

        max_attempts = 10
        poll_interval_s = 2.0

        async with httpx.AsyncClient(
            base_url=self._settings.base_url, timeout=5.0
        ) as client:
            for attempt in range(1, max_attempts + 1):
                try:
                    resp = await client.get(self._settings.status_path)
                    resp.raise_for_status()
                    status = resp.json()
                    bundle_status = (
                        status.get("bundles", {})
                              .get(self._settings.expected_bundle_name, {})
                    )
                    revision = bundle_status.get("active_revision") or ""
                    if revision:
                        info = BundleInfo(
                            version    = revision,
                            loaded_at  = datetime.now(tz=timezone.utc),
                            source_url = self._settings.base_url,
                        )
                        logger.info(
                            "PolicyBundleLoader: bundle '%s' active at revision=%s",
                            self._settings.expected_bundle_name, revision,
                        )
                        return info
                except Exception as exc:
                    logger.warning(
                        "PolicyBundleLoader: attempt %d/%d failed: %s",
                        attempt, max_attempts, exc,
                    )
                await asyncio.sleep(poll_interval_s)

        raise BundleNotReadyError(
            f"OPA bundle '{self._settings.expected_bundle_name}' not active after "
            f"{max_attempts} attempts"
        )
```

**Lifespan integration:**

```python
# src/gateway/lifespan.py — extend startup block
from src.governance.opa.client        import OPAClient
from src.governance.opa.bundle_loader import PolicyBundleLoader, BundleNotReadyError

bundle_loader = PolicyBundleLoader()
try:
    bundle_info = await bundle_loader.verify()
except BundleNotReadyError:
    logger.critical("OPA bundle not ready — refusing to start")
    raise   # prevent gateway from serving requests with no policy

opa_client = OPAClient()
app.state.opa_client    = opa_client
app.state.bundle_info   = bundle_info

# Shutdown
await app.state.opa_client.close()
```

## Acceptance Criteria

- [ ] `OPAClient.evaluate_chunk()` sends `{"input": {...}}` to `POST /v1/data/contextiq/authz/allow`
- [ ] `ChunkAuthzInput` fields `user_roles`, `tenant_id`, `source_id`, `classification_label` are all present in the serialised `input` payload
- [ ] `OPAEvaluationError` is raised on HTTP 5xx or timeout (not swallowed)
- [ ] `evaluate_batch()` processes chunks concurrently — verified by asserting `total_eval_ms < n_chunks × request_timeout_ms` for `n_chunks > concurrency`
- [ ] `PolicyBundleLoader.verify()` raises `BundleNotReadyError` when the bundle status endpoint never returns a revision
- [ ] `PolicyBundleLoader.verify()` returns `BundleInfo` with the correct `version` when the bundle is active
- [ ] `deny_reason` fetch failure is silently absorbed — denial is still recorded with empty rationale

## Dependencies

- TASK-US032-01 (`ChunkAuthzInput`, `PolicyDecision`, `AuthzFilterResult`, `BundleInfo`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `httpx.AsyncClient` via `respx`; no live OPA sidecar in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
