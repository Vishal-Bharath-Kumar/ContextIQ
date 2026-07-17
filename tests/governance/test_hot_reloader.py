"""Tests for PolicyHotReloader — TASK-US032-03.

All HTTP calls are mocked with respx; asyncio.sleep is patched to fast-forward
poll cycles without real wall-clock delays.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from src.governance.opa.hot_reloader import HotReloadSettings, PolicyHotReloader
from src.governance.opa.schemas import BundleInfo

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STATUS_URL = "http://localhost:8181/v1/status"
BUNDLE_NAME = "contextiq_policies"


@pytest.fixture
def settings() -> HotReloadSettings:
    return HotReloadSettings(
        poll_interval_s=1.0,
        status_url=STATUS_URL,
        bundle_name=BUNDLE_NAME,
        request_timeout_s=5.0,
    )


@pytest.fixture
def initial_bundle() -> BundleInfo:
    return BundleInfo(
        version="v1.0.0",
        loaded_at=datetime(2024, 1, 1, tzinfo=UTC),
        source_url=STATUS_URL,
    )


@pytest.fixture
def reloader(initial_bundle: BundleInfo, settings: HotReloadSettings) -> PolicyHotReloader:
    return PolicyHotReloader(initial_bundle=initial_bundle, settings=settings)


def _status_response(revision: str) -> dict[str, Any]:
    return {
        "bundles": {
            BUNDLE_NAME: {
                "active_revision": revision,
            }
        }
    }


# ---------------------------------------------------------------------------
# AC: current_bundle reflects initial bundle before any poll
# ---------------------------------------------------------------------------

def test_initial_bundle_accessible(
    reloader: PolicyHotReloader, initial_bundle: BundleInfo
) -> None:
    assert reloader.current_bundle is initial_bundle


# ---------------------------------------------------------------------------
# AC: when active_revision changes, current_bundle.version is updated
# ---------------------------------------------------------------------------

@respx.mock
async def test_revision_change_updates_current_bundle(
    reloader: PolicyHotReloader,
) -> None:
    """When active_revision in OPA differs, _current is replaced with new version."""
    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(200, json=_status_response("v2.0.0"))
    )

    async with httpx.AsyncClient(timeout=5.0) as client:
        await reloader._poll_once(client)

    assert reloader.current_bundle.version == "v2.0.0"
    assert reloader.current_bundle.source_url == STATUS_URL


# ---------------------------------------------------------------------------
# AC: when active_revision is unchanged, current_bundle object is not replaced
# ---------------------------------------------------------------------------

@respx.mock
async def test_same_revision_does_not_replace_bundle(
    reloader: PolicyHotReloader, initial_bundle: BundleInfo
) -> None:
    """No object replacement when active_revision matches current version."""
    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(200, json=_status_response("v1.0.0"))
    )

    async with httpx.AsyncClient(timeout=5.0) as client:
        await reloader._poll_once(client)

    assert reloader.current_bundle is initial_bundle


# ---------------------------------------------------------------------------
# AC: on_reload callback invoked exactly once per detected revision change
# ---------------------------------------------------------------------------

@respx.mock
async def test_on_reload_callback_invoked_once_per_change(
    reloader: PolicyHotReloader,
) -> None:
    callback = MagicMock()
    reloader.on_reload(callback)

    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(200, json=_status_response("v2.0.0"))
    )

    async with httpx.AsyncClient(timeout=5.0) as client:
        await reloader._poll_once(client)
        # Second poll — same revision, callback should not fire again
        await reloader._poll_once(client)

    callback.assert_called_once()


# ---------------------------------------------------------------------------
# AC: callback error is swallowed — does not propagate
# ---------------------------------------------------------------------------

@respx.mock
async def test_callback_error_does_not_propagate(
    reloader: PolicyHotReloader,
) -> None:
    def bad_callback() -> None:
        raise RuntimeError("boom")

    reloader.on_reload(bad_callback)

    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(200, json=_status_response("v3.0.0"))
    )

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Must not raise
        await reloader._poll_once(client)

    assert reloader.current_bundle.version == "v3.0.0"


# ---------------------------------------------------------------------------
# AC: poll failure (HTTP error) is logged and loop continues
# ---------------------------------------------------------------------------

@respx.mock
async def test_http_error_does_not_propagate_from_run(
    reloader: PolicyHotReloader,
) -> None:
    """HTTP failures during poll are caught; run() continues and does not raise."""
    call_count = 0

    async def _fake_sleep(secs: float) -> None:  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            reloader.stop()

    respx.get(STATUS_URL).mock(return_value=httpx.Response(500))

    with patch("src.governance.opa.hot_reloader.asyncio.sleep", side_effect=_fake_sleep):
        await reloader.run()  # must return without raising

    # loop ran exactly `call_count` cycles
    assert call_count >= 2
    # bundle unchanged despite errors
    assert reloader.current_bundle.version == "v1.0.0"


# ---------------------------------------------------------------------------
# AC: stop() causes run() to exit after the current sleep period
# ---------------------------------------------------------------------------

async def test_stop_exits_run_loop(
    reloader: PolicyHotReloader, initial_bundle: BundleInfo
) -> None:
    """stop() sets _running=False; run() exits after the next sleep wakeup."""
    sleep_count = 0

    async def _fake_sleep(secs: float) -> None:  # noqa: ARG001
        nonlocal sleep_count
        sleep_count += 1
        reloader.stop()

    with (
        patch("src.governance.opa.hot_reloader.asyncio.sleep", side_effect=_fake_sleep),
        respx.mock,
    ):
        respx.get(STATUS_URL).mock(
            return_value=httpx.Response(200, json=_status_response("v1.0.0"))
        )
        await reloader.run()

    assert sleep_count == 1
    assert reloader.current_bundle is initial_bundle


# ---------------------------------------------------------------------------
# AC: run() polls poll_interval_s after each wake — call count assertion
# ---------------------------------------------------------------------------

async def test_run_calls_sleep_with_correct_interval(
    reloader: PolicyHotReloader,
) -> None:
    """asyncio.sleep is called with poll_interval_s each iteration."""
    sleep_calls: list[float] = []

    async def _fake_sleep(secs: float) -> None:
        sleep_calls.append(secs)
        if len(sleep_calls) >= 3:
            reloader.stop()

    with (
        patch("src.governance.opa.hot_reloader.asyncio.sleep", side_effect=_fake_sleep),
        respx.mock,
    ):
        respx.get(STATUS_URL).mock(
            return_value=httpx.Response(200, json=_status_response("v1.0.0"))
        )
        await reloader.run()

    assert len(sleep_calls) == 3
    assert all(s == 1.0 for s in sleep_calls)


# ---------------------------------------------------------------------------
# AC: empty active_revision does not replace current bundle
# ---------------------------------------------------------------------------

@respx.mock
async def test_empty_revision_does_not_update_bundle(
    reloader: PolicyHotReloader, initial_bundle: BundleInfo
) -> None:
    """An empty active_revision (bundle not yet active) is silently ignored."""
    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(200, json={"bundles": {BUNDLE_NAME: {}}})
    )

    async with httpx.AsyncClient(timeout=5.0) as client:
        await reloader._poll_once(client)

    assert reloader.current_bundle is initial_bundle


# ---------------------------------------------------------------------------
# AC: missing bundle key in status response is handled gracefully
# ---------------------------------------------------------------------------

@respx.mock
async def test_missing_bundle_key_does_not_update_bundle(
    reloader: PolicyHotReloader, initial_bundle: BundleInfo
) -> None:
    """If the bundle name is absent from the status response, nothing changes."""
    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(200, json={"bundles": {}})
    )

    async with httpx.AsyncClient(timeout=5.0) as client:
        await reloader._poll_once(client)

    assert reloader.current_bundle is initial_bundle


# ---------------------------------------------------------------------------
# TASK-US032-05 — AC-6: hot-reload detects bundle revision change (named per AC)
# ---------------------------------------------------------------------------

@respx.mock
async def test_hot_reloader_detects_revision_change() -> None:
    """AC-6: when active_revision changes, current_bundle.version is updated and
    on_reload callback is invoked within a single poll cycle."""
    from datetime import UTC, datetime

    initial = BundleInfo(
        version="v1.0.0",
        loaded_at=datetime.now(tz=UTC),
        source_url=STATUS_URL,
    )
    settings = HotReloadSettings(
        poll_interval_s=0.01,
        status_url=STATUS_URL,
        bundle_name=BUNDLE_NAME,
    )
    reloader = PolicyHotReloader(initial, settings)
    reloaded: list[bool] = []
    reloader.on_reload(lambda: reloaded.append(True))

    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(
            200,
            json={"bundles": {BUNDLE_NAME: {"active_revision": "v1.1.0"}}},
        )
    )

    async with httpx.AsyncClient(timeout=5.0) as client:
        await reloader._poll_once(client)

    assert reloader.current_bundle.version == "v1.1.0"
    assert len(reloaded) == 1


# ---------------------------------------------------------------------------
# TASK-US032-05 — AC-6: no update on same revision (named per AC)
# ---------------------------------------------------------------------------

@respx.mock
async def test_hot_reloader_no_update_on_same_revision() -> None:
    """AC-6: when active_revision is unchanged, current_bundle object is not replaced."""
    from datetime import UTC, datetime

    initial = BundleInfo(
        version="v1.0.0",
        loaded_at=datetime.now(tz=UTC),
        source_url=STATUS_URL,
    )
    settings = HotReloadSettings(
        poll_interval_s=0.01,
        status_url=STATUS_URL,
        bundle_name=BUNDLE_NAME,
    )
    reloader = PolicyHotReloader(initial, settings)

    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(
            200,
            json={"bundles": {BUNDLE_NAME: {"active_revision": "v1.0.0"}}},
        )
    )

    original_bundle = reloader.current_bundle

    async with httpx.AsyncClient(timeout=5.0) as client:
        await reloader._poll_once(client)

    assert reloader.current_bundle is original_bundle  # same object, not replaced
