"""Startup verification helpers for local Ollama-backed agent models."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from src.llm.local_ollama_chain import get_ollama_base_url
from src.model_registry.services.ollama_service import OllamaService

logger = logging.getLogger(__name__)


def default_ollama_verification_status() -> dict[str, Any]:
    return {
        "status": "unknown",
        "base_url": get_ollama_base_url(),
        "checks": [],
        "installed_models": [],
        "missing_models": [],
    }


async def verify_ollama_models_available(model_ids: Iterable[str]) -> dict[str, Any]:
    """Best-effort startup verification for configured local Ollama models.

    Returns a structured status payload and logs warnings when models are
    missing or Ollama is unreachable. This never raises.
    """

    base = default_ollama_verification_status()
    required_models = [
        model_id.removeprefix("ollama/")
        for model_id in model_ids
        if isinstance(model_id, str) and model_id.startswith("ollama/")
    ]
    if not required_models:
        base["status"] = "skipped"
        return base

    service = OllamaService(base_url=get_ollama_base_url())
    try:
        installed_models = await service.list_models()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ollama startup verification skipped: %s", exc)
        base["status"] = "unreachable"
        base["error"] = str(exc)
        base["checks"] = [_build_check(required, installed_names=[]) for required in required_models]
        return base

    installed_names = sorted(model.name.removeprefix("ollama/") for model in installed_models)
    checks = [_build_check(required, installed_names=installed_names) for required in required_models]
    missing = sorted(check["requested"] for check in checks if not check["satisfied"])
    base["checks"] = checks
    base["installed_models"] = installed_names
    base["missing_models"] = missing

    if missing:
        logger.warning(
            "Ollama startup verification: missing local models %s at %s",
            missing,
            get_ollama_base_url(),
        )
        base["status"] = "missing_models"
    else:
        base["status"] = "ok"

    return base


def _build_check(required: str, *, installed_names: list[str]) -> dict[str, Any]:
    match_mode = "exact_tag" if ":" in required else "bare_or_latest"
    satisfied_by = _match_model(required, installed_names)
    return {
        "requested": required,
        "match_mode": match_mode,
        "satisfied": satisfied_by is not None,
        "satisfied_by": satisfied_by,
    }


def _match_model(required: str, installed_names: list[str]) -> str | None:
    if ":" in required:
        return required if required in installed_names else None

    if required in installed_names:
        return required

    latest = f"{required}:latest"
    if latest in installed_names:
        return latest

    return None
