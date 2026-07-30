"""Helpers for exposing OPA startup state on health endpoints."""

from __future__ import annotations

from typing import Any


def default_opa_health_status() -> dict[str, Any]:
    return {
        "status": "unknown",
        "configured": False,
        "bundle_ready": False,
        "degraded": False,
        "bundle_version": None,
        "error": None,
    }


def opa_health_status(
    *,
    configured: bool,
    bundle_ready: bool,
    degraded: bool,
    bundle_version: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "status": _opa_status_value(configured=configured, bundle_ready=bundle_ready, degraded=degraded),
        "configured": configured,
        "bundle_ready": bundle_ready,
        "degraded": degraded,
        "bundle_version": bundle_version,
        "error": error,
    }


def _opa_status_value(*, configured: bool, bundle_ready: bool, degraded: bool) -> str:
    if not configured:
        return "disabled"
    if bundle_ready:
        return "ready"
    if degraded:
        return "degraded"
    return "unready"
