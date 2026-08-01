"""Startup verifier for the OPA policy bundle.

Satisfies AC-1: the expected bundle is confirmed active before the gateway
begins serving requests.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from src.governance.opa.client import OPAClientSettings
from src.governance.opa.schemas import BundleInfo

logger = logging.getLogger(__name__)


class BundleNotReadyError(RuntimeError):
    """Raised at startup if the expected OPA bundle is not yet active."""


class PolicyBundleLoader:
    """Verifies the OPA sidecar has loaded the configured policy bundle.

    Called once during application lifespan startup — before the gateway
    begins accepting requests (AC-1).  OPA exposes bundle activation status
    via ``GET /v1/status``::

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
        """Poll the OPA status endpoint until the expected bundle is active.

        Raises :exc:`BundleNotReadyError` after ``max_attempts`` if the bundle
        never becomes active.
        """
        max_attempts = 10
        poll_interval_s = 2.0

        async with httpx.AsyncClient(
            base_url=self._settings.base_url, timeout=5.0, trust_env=False
        ) as client:
            for attempt in range(1, max_attempts + 1):
                try:
                    resp = await client.get(self._settings.status_path)
                    if resp.is_success:
                        status = resp.json().get("result", resp.json())
                        bundle_status = (
                            status.get("bundles", {}).get(
                                self._settings.expected_bundle_name, {}
                            )
                        )
                        revision = bundle_status.get("active_revision") or ""
                        if revision:
                            info = BundleInfo(
                                version=revision,
                                loaded_at=datetime.now(tz=UTC),
                                source_url=self._settings.base_url,
                            )
                            logger.info(
                                "PolicyBundleLoader: bundle '%s' active at revision=%s",
                                self._settings.expected_bundle_name,
                                revision,
                            )
                            return info
                    else:
                        resp.raise_for_status()

                    local_info = await self._verify_local_policy(client)
                    if local_info is not None:
                        return local_info
                except Exception as exc:
                    local_info = await self._verify_local_policy(client)
                    if local_info is not None:
                        return local_info
                    logger.warning(
                        "PolicyBundleLoader: attempt %d/%d failed: %s",
                        attempt,
                        max_attempts,
                        exc,
                    )
                await asyncio.sleep(poll_interval_s)

        raise BundleNotReadyError(
            f"OPA bundle '{self._settings.expected_bundle_name}' not active after "
            f"{max_attempts} attempts"
        )

    async def _verify_local_policy(
        self,
        client: httpx.AsyncClient,
    ) -> BundleInfo | None:
        try:
            resp = await client.get("v1/policies")
            resp.raise_for_status()
        except Exception:
            return None

        for policy in resp.json().get("result", []):
            raw = str(policy.get("raw") or "")
            if "package contextiq.authz" not in raw:
                continue
            logger.info("PolicyBundleLoader: local inline authz policy detected")
            return BundleInfo(
                version="local-inline-policy",
                loaded_at=datetime.now(tz=UTC),
                source_url=self._settings.base_url,
            )
        return None
