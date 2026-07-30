from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.ollama_verify import default_ollama_verification_status, verify_ollama_models_available


def _model(name: str) -> MagicMock:
    model = MagicMock()
    model.name = name
    return model


@pytest.mark.asyncio
async def test_bare_model_matches_latest_tag() -> None:
    with patch("src.llm.ollama_verify.OllamaService.list_models", new=AsyncMock(return_value=[_model("llama3.2:latest")])):
        result = await verify_ollama_models_available(["ollama/llama3.2"])

    assert result["status"] == "ok"
    assert result["checks"][0]["satisfied_by"] == "llama3.2:latest"
    assert result["checks"][0]["match_mode"] == "bare_or_latest"


@pytest.mark.asyncio
async def test_specific_tag_requires_exact_match() -> None:
    with patch("src.llm.ollama_verify.OllamaService.list_models", new=AsyncMock(return_value=[_model("llama3.2")])):
        result = await verify_ollama_models_available(["ollama/llama3.2:latest"])

    assert result["status"] == "missing_models"
    assert result["checks"][0]["satisfied"] is False
    assert result["missing_models"] == ["llama3.2:latest"]


@pytest.mark.asyncio
async def test_unreachable_ollama_returns_unreachable_status() -> None:
    with patch("src.llm.ollama_verify.OllamaService.list_models", new=AsyncMock(side_effect=RuntimeError("down"))):
        result = await verify_ollama_models_available(["ollama/llama3.2"])

    assert result["status"] == "unreachable"
    assert result["checks"][0]["satisfied"] is False
    assert result["error"] == "down"


def test_default_status_shape() -> None:
    result = default_ollama_verification_status()
    assert result["status"] == "unknown"
    assert result["checks"] == []
    assert result["installed_models"] == []
    assert result["missing_models"] == []