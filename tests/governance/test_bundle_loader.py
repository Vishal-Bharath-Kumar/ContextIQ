"""Tests for PolicyBundleLoader — TASK-US032-05 (AC-1).

AC-1: OPA bundle is confirmed active at startup before the gateway accepts requests.
All HTTP calls are mocked with respx; asyncio.sleep is patched to fast-forward
polling cycles without real wall-clock delays.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from src.governance.opa.bundle_loader import BundleNotReadyError, PolicyBundleLoader
from src.governance.opa.client import OPAClientSettings


# ---------------------------------------------------------------------------
# AC-1: verify() returns BundleInfo when bundle is active
# ---------------------------------------------------------------------------

@respx.mock
async def test_bundle_loader_returns_bundle_info_when_ready() -> None:
    """AC-1: PolicyBundleLoader.verify() returns BundleInfo with correct version
    and a timezone-aware loaded_at timestamp when the bundle is active."""
    respx.get("http://localhost:8181/v1/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "bundles": {
                    "contextiq_policies": {"active_revision": "v1.2.3"}
                }
            },
        )
    )

    settings = OPAClientSettings(expected_bundle_name="contextiq_policies")
    loader = PolicyBundleLoader(settings)
    info = await loader.verify()

    assert info.version == "v1.2.3"
    assert isinstance(info.loaded_at, datetime)
    assert info.loaded_at.tzinfo is not None


# ---------------------------------------------------------------------------
# AC-1: verify() raises BundleNotReadyError when bundle never activates
# ---------------------------------------------------------------------------

@respx.mock
async def test_bundle_loader_raises_when_bundle_never_activates() -> None:
    """AC-1: BundleNotReadyError is raised when active_revision is never present.

    asyncio.sleep is patched to a no-op so the 10-attempt loop runs instantly.
    """
    respx.get("http://localhost:8181/v1/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "bundles": {"contextiq_policies": {}}  # no active_revision
            },
        )
    )

    settings = OPAClientSettings(expected_bundle_name="contextiq_policies")
    loader = PolicyBundleLoader(settings)

    with patch("src.governance.opa.bundle_loader.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(BundleNotReadyError):
            await loader.verify()


@respx.mock
async def test_bundle_loader_accepts_local_inline_policy_when_status_unavailable() -> None:
    respx.get("http://localhost:8181/v1/status").mock(
        return_value=httpx.Response(
            500,
            json={"code": "internal_error", "message": "status plugin not enabled"},
        )
    )
    respx.get("http://localhost:8181/v1/policies").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": [
                    {
                        "id": "contextiq_authz.rego",
                        "raw": "package contextiq.authz\n\ndefault allow := false",
                    }
                ]
            },
        )
    )

    settings = OPAClientSettings(expected_bundle_name="contextiq_policies")
    loader = PolicyBundleLoader(settings)
    info = await loader.verify()

    assert info.version == "local-inline-policy"
