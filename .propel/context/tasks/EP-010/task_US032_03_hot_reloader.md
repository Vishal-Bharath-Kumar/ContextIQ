# TASK-US032-03 — `PolicyHotReloader`: 60 s Background Bundle Refresh

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US032-03 |
| User Story | US-032 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `PolicyHotReloader` — a background `asyncio.Task` that polls the OPA sidecar status endpoint every `poll_interval_s` (default 30 s), detects bundle revision changes, and updates the application-level `BundleInfo` state so that `opa_filter_node()` always reports the current bundle version. Satisfies AC-6 (updated bundles take effect within 60 s without platform restart).

## Implementation Details

**Technology:** Python 3.11+, `httpx[asyncio]>=0.27`, `asyncio`, `pydantic-settings`

**File locations:**
- `src/governance/opa/hot_reloader.py` — `PolicyHotReloader`, `HotReloadSettings`
- `src/gateway/lifespan.py` — extend lifespan to start/stop the reloader
- `tests/governance/test_hot_reloader.py`

---

### `HotReloadSettings`

```python
# src/governance/opa/hot_reloader.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class HotReloadSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPA_RELOAD_", env_file=".env")

    # Poll interval in seconds. Two polls within 60 s guarantees AC-6 compliance.
    poll_interval_s: float = 30.0
    # OPA status endpoint (same as OPAClientSettings.status_path).
    status_url:      str   = "http://localhost:8181/v1/status"
    # Bundle name to monitor for revision changes.
    bundle_name:     str   = "contextiq_policies"
    # HTTP timeout for the status poll call.
    request_timeout_s: float = 5.0
```

---

### Hot-reload mechanism

OPA's bundle reload is managed **by the OPA sidecar itself**, not by the Python application. The OPA sidecar is configured with a bundle source (e.g. S3 bucket) and a `polling.min_delay_seconds` / `polling.max_delay_seconds` config. When OPA detects a new bundle revision, it loads it atomically.

`PolicyHotReloader`'s role is to:
1. Detect when OPA's `active_revision` has changed (by polling `/v1/status`).
2. Update `app.state.bundle_info` with the new revision.
3. Log the change so operators and audit tools can track bundle history.
4. Expose the current `BundleInfo` to `opa_filter_node()` so every evaluation records the correct version.

The Python application does **not** push bundles to OPA. Bundle distribution is OPA's responsibility.

---

### `PolicyHotReloader`

```python
# src/governance/opa/hot_reloader.py (continued)
import asyncio
import logging
from datetime import datetime, timezone

import httpx

from src.governance.opa.schemas import BundleInfo

logger = logging.getLogger(__name__)


class PolicyHotReloader:
    """
    Background task that detects OPA bundle revision changes and updates
    the application's BundleInfo reference.

    Usage:
        reloader = PolicyHotReloader(current_bundle_info, settings)
        task     = asyncio.create_task(reloader.run(), name="policy_hot_reloader")

    Stop via:
        reloader.stop()
        task.cancel()
    """

    def __init__(
        self,
        initial_bundle: BundleInfo,
        settings:       HotReloadSettings | None = None,
    ) -> None:
        self._current  = initial_bundle
        self._settings = settings or HotReloadSettings()
        self._running  = False
        # Callbacks registered by external components to be notified on reload.
        self._on_reload_callbacks: list = []

    @property
    def current_bundle(self) -> BundleInfo:
        return self._current

    def on_reload(self, callback) -> None:
        """Register a zero-argument callable invoked after each bundle update."""
        self._on_reload_callbacks.append(callback)

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        """
        Poll OPA status every poll_interval_s. Detect revision changes and
        update self._current. Non-fatal: errors are logged and the loop continues.
        """
        self._running = True
        logger.info(
            "PolicyHotReloader: started (poll_interval=%ss, bundle=%s)",
            self._settings.poll_interval_s, self._settings.bundle_name,
        )

        async with httpx.AsyncClient(timeout=self._settings.request_timeout_s) as client:
            while self._running:
                await asyncio.sleep(self._settings.poll_interval_s)
                try:
                    await self._poll_once(client)
                except Exception as exc:
                    logger.warning(
                        "PolicyHotReloader: poll failed: %s — retrying next interval", exc
                    )

        logger.info("PolicyHotReloader: stopped")

    async def _poll_once(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(self._settings.status_url)
        resp.raise_for_status()

        bundle_status = (
            resp.json()
                .get("bundles", {})
                .get(self._settings.bundle_name, {})
        )
        new_revision = bundle_status.get("active_revision") or ""

        if not new_revision or new_revision == self._current.version:
            return

        old_version   = self._current.version
        self._current = BundleInfo(
            version    = new_revision,
            loaded_at  = datetime.now(tz=timezone.utc),
            source_url = self._settings.status_url,
        )
        logger.info(
            "PolicyHotReloader: bundle updated %s → %s",
            old_version, new_revision,
        )
        for cb in self._on_reload_callbacks:
            try:
                cb()
            except Exception:
                logger.exception("PolicyHotReloader: callback error — ignored")
```

---

### Lifespan integration

```python
# src/gateway/lifespan.py — extend startup block (after bundle_loader.verify())
from src.governance.opa.hot_reloader import PolicyHotReloader, HotReloadSettings

hot_reloader      = PolicyHotReloader(bundle_info)
hot_reloader_task = asyncio.create_task(
    hot_reloader.run(),
    name="policy_hot_reloader",
)
app.state.hot_reloader = hot_reloader

yield

# Shutdown
hot_reloader.stop()
hot_reloader_task.cancel()
```

**60-second SLA (AC-6):**

With `poll_interval_s=30`, the maximum time between a bundle update in the OPA sidecar and the Python application detecting it is 30 s. Combined with OPA's own bundle polling (typically configured at 30–60 s), the end-to-end propagation delay from policy repository to active evaluation is ≤ 60 s, satisfying AC-6. Setting `poll_interval_s=15` gives a safety margin for the 60 s SLA if OPA's bundle download takes up to 45 s.

**Why `app.state` and not a Redis key:**

`BundleInfo` is process-local metadata — it does not need to be shared across instances. Each pod's `PolicyHotReloader` independently detects bundle changes from the OPA sidecar running in its own pod. There is no cross-pod coordination requirement.

## Acceptance Criteria

- [ ] `PolicyHotReloader.run()` polls every `poll_interval_s` — verified by asserting call count after `n × poll_interval_s`
- [ ] When `active_revision` changes, `current_bundle.version` is updated
- [ ] When `active_revision` is unchanged, `current_bundle` is not replaced (same object)
- [ ] `on_reload` callback is invoked exactly once per detected revision change
- [ ] Poll failure (HTTP error) is logged and the loop continues — no exception propagated to caller
- [ ] `stop()` causes `run()` to exit after the current sleep period

## Dependencies

- TASK-US032-01 (`BundleInfo`)
- TASK-US032-02 (`OPAClientSettings` — `status_url` reuses same OPA base URL)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `httpx.AsyncClient` via `respx`; use `asyncio.sleep` patching to fast-forward poll cycles
- [ ] `mypy --strict` passes; no `ruff` lint errors
