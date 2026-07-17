"""Background hot-reloader for OPA policy bundle revision tracking.

Satisfies AC-6: updated bundles take effect within 60 s without platform
restart.  The OPA sidecar handles actual bundle distribution; this module
detects when the sidecar has loaded a new revision and updates the
application-level ``BundleInfo`` reference so every subsequent evaluation
records the correct bundle version.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.governance.opa.schemas import BundleInfo

logger = logging.getLogger(__name__)


class HotReloadSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPA_RELOAD_", env_file=".env", extra="ignore")

    # Poll interval in seconds.  Two polls within 60 s guarantees AC-6 compliance.
    poll_interval_s: float = 30.0
    # OPA status endpoint (same base URL as OPAClientSettings).
    status_url: str = "http://localhost:8181/v1/status"
    # Bundle name to monitor for revision changes.
    bundle_name: str = "contextiq_policies"
    # HTTP timeout for each status poll request.
    request_timeout_s: float = 5.0


class PolicyHotReloader:
    """Background task that detects OPA bundle revision changes.

    Polls the OPA sidecar ``/v1/status`` endpoint every ``poll_interval_s``
    seconds.  When the ``active_revision`` field for the configured bundle
    changes, the internal ``BundleInfo`` reference is replaced and registered
    callbacks are invoked.

    Usage::

        reloader = PolicyHotReloader(bundle_info)
        task = asyncio.create_task(reloader.run(), name="policy_hot_reloader")

    Stop via::

        reloader.stop()
        task.cancel()
    """

    def __init__(
        self,
        initial_bundle: BundleInfo,
        settings: HotReloadSettings | None = None,
    ) -> None:
        self._current = initial_bundle
        self._settings = settings or HotReloadSettings()
        self._running = False
        self._on_reload_callbacks: list[Callable[[], None]] = []

    @property
    def current_bundle(self) -> BundleInfo:
        """Return the currently active ``BundleInfo``."""
        return self._current

    def on_reload(self, callback: Callable[[], None]) -> None:
        """Register a zero-argument callable invoked after each bundle update."""
        self._on_reload_callbacks.append(callback)

    def stop(self) -> None:
        """Signal the polling loop to exit after the current sleep period."""
        self._running = False

    async def run(self) -> None:
        """Poll OPA status every ``poll_interval_s`` seconds.

        Errors during a poll are logged and the loop continues — they are
        non-fatal so a transient OPA hiccup does not crash the application.
        """
        self._running = True
        logger.info(
            "PolicyHotReloader: started (poll_interval=%ss, bundle=%s)",
            self._settings.poll_interval_s,
            self._settings.bundle_name,
        )

        async with httpx.AsyncClient(timeout=self._settings.request_timeout_s) as client:
            while self._running:
                await asyncio.sleep(self._settings.poll_interval_s)
                try:
                    await self._poll_once(client)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "PolicyHotReloader: poll failed: %s — retrying next interval",
                        exc,
                    )

        logger.info("PolicyHotReloader: stopped")

    async def _poll_once(self, client: httpx.AsyncClient) -> None:
        """Perform a single status poll and update ``_current`` if revision changed."""
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

        old_version = self._current.version
        self._current = BundleInfo(
            version=new_revision,
            loaded_at=datetime.now(tz=UTC),
            source_url=self._settings.status_url,
        )
        logger.info(
            "PolicyHotReloader: bundle updated %s → %s",
            old_version,
            new_revision,
        )
        for cb in self._on_reload_callbacks:
            try:
                cb()
            except Exception:  # noqa: BLE001
                logger.exception("PolicyHotReloader: callback error — ignored")
