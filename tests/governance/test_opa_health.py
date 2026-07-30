from __future__ import annotations

from src.governance.opa.health import default_opa_health_status, opa_health_status


def test_default_opa_health_status_shape() -> None:
    status = default_opa_health_status()
    assert status == {
        "status": "unknown",
        "configured": False,
        "bundle_ready": False,
        "degraded": False,
        "bundle_version": None,
        "error": None,
    }


def test_opa_ready_status() -> None:
    status = opa_health_status(
        configured=True,
        bundle_ready=True,
        degraded=False,
        bundle_version="rev-123",
    )
    assert status["status"] == "ready"
    assert status["bundle_version"] == "rev-123"


def test_opa_degraded_status() -> None:
    status = opa_health_status(
        configured=True,
        bundle_ready=False,
        degraded=True,
        error="OPA bundle not ready",
    )
    assert status["status"] == "degraded"
    assert status["error"] == "OPA bundle not ready"


def test_opa_disabled_status() -> None:
    status = opa_health_status(configured=False, bundle_ready=False, degraded=False)
    assert status["status"] == "disabled"