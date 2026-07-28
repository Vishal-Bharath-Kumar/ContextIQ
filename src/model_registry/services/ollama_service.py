"""Service for managing Ollama model installation and lifecycle.

Handles pulling models, checking availability, and gathering metadata
for automatic registration in the Model Registry.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from src.model_registry.schemas.model_installation import (
    OllamaModelInfo,
    OllamaPullRequest,
    OllamaPullResponse,
)


class OllamaService:
    """Service for interacting with Ollama API."""
    
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = base_url or os.getenv(
            "OLLAMA_BASE_URL",
            "http://localhost:11434"
        )
        # Handle Docker internal networking
        if self.base_url == "http://host.docker.internal:11434":
            self.base_url = "http://host.docker.internal:11434"
    
    async def list_models(self) -> list[OllamaModelInfo]:
        """List all downloaded Ollama models."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
                
                models = []
                for model in data.get("models", []):
                    models.append(OllamaModelInfo(
                        name=model["name"],
                        size=model.get("size", 0),
                        digest=model.get("digest", ""),
                        modified_at=model.get("modified_at", ""),
                    ))
                return models
            except httpx.HTTPError as e:
                raise HTTPException(
                    status_code=503,
                    detail=f"Failed to connect to Ollama: {str(e)}"
                )
    
    async def pull_model(self, request: OllamaPullRequest) -> OllamaPullResponse:
        """Pull/download an Ollama model."""
        pull_timeout_seconds = float(os.getenv("OLLAMA_PULL_TIMEOUT_SECONDS", "300"))

        # Use explicit timeout controls so we can distinguish long downloads from connectivity issues.
        timeout = httpx.Timeout(
            connect=10.0,
            read=pull_timeout_seconds,
            write=30.0,
            pool=10.0,
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                # Start the pull
                response = await client.post(
                    f"{self.base_url}/api/pull",
                    json={"name": request.model_name},
                )
                response.raise_for_status()
                
                # Ollama streams progress, we'll read the final status
                lines = response.text.strip().split("\n")
                final_status = {}
                error_message = None
                
                for line in lines:
                    if line:
                        import json
                        line_data = json.loads(line)
                        # Check for error in any line
                        if "error" in line_data:
                            error_message = line_data["error"]
                            break
                        # Keep updating with each line (final line is the status)
                        final_status = line_data
                
                # If there was an error, raise it
                if error_message:
                    raise ValueError(f"Ollama pull failed: {error_message}")
                
                # If we have no final status, something went wrong
                if not final_status:
                    raise ValueError(f"No response from Ollama while pulling '{request.model_name}'")
                
                status = final_status.get("status", "")
                
                # Check for success
                is_success = status.lower() == "success" or "success" in status.lower()
                
                return OllamaPullResponse(
                    status="success" if is_success else "failed",
                    model_name=request.model_name,
                    message=f"Model '{request.model_name}' pulled successfully" if is_success else f"Pull ended with status: {status or 'unknown'}",
                    digest=final_status.get("digest"),
                )
            except httpx.ReadTimeout:
                raise HTTPException(
                    status_code=504,
                    detail=(
                        f"Timed out while pulling Ollama model '{request.model_name}'. "
                        "The download is taking longer than the API timeout window. "
                        "Try pulling it directly with `ollama pull <model>` and then install again."
                    ),
                )
            except httpx.HTTPError as e:
                raise HTTPException(
                    status_code=503,
                    detail=f"Failed to pull Ollama model: {str(e)}"
                )
    
    async def get_model_info(self, model_name: str) -> Optional[dict[str, Any]]:
        """Get detailed information about a specific model."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/show",
                    json={"name": model_name},
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError:
                return None
    
    async def check_model_exists(self, model_name: str) -> bool:
        """Check if a model is already downloaded."""
        models = await self.list_models()
        # Normalize model names (handle :latest suffix)
        normalized_name = model_name.replace(":latest", "")
        return any(
            m.name.replace(":latest", "") == normalized_name
            for m in models
        )
    
    async def delete_model(self, model_name: str) -> dict[str, str]:
        """Delete an Ollama model from local storage."""
        async with httpx.AsyncClient() as client:
            try:
                # Use request() method since delete() doesn't support json parameter
                response = await client.request(
                    "DELETE",
                    f"{self.base_url}/api/delete",
                    json={"name": model_name},
                )
                
                # 404 means model doesn't exist - that's fine, goal is to remove it
                if response.status_code == 404:
                    return {
                        "status": "success",
                        "message": f"Model '{model_name}' was not found in Ollama (already deleted or never existed)",
                    }
                
                response.raise_for_status()
                return {
                    "status": "success",
                    "message": f"Model '{model_name}' deleted successfully from Ollama",
                }
            except httpx.HTTPStatusError as e:
                # Re-raise with more context
                raise HTTPException(
                    status_code=503,
                    detail=f"Failed to delete Ollama model '{model_name}': {e.response.status_code} - {e.response.text}"
                )
            except httpx.HTTPError as e:
                # Connection errors, timeouts, etc.
                raise HTTPException(
                    status_code=503,
                    detail=f"Failed to connect to Ollama: {str(e)}"
                )
    
    async def estimate_context_window(self, model_name: str) -> int:
        """Estimate context window based on model name."""
        # Common Ollama model context windows
        context_map = {
            "llama3.2": 128000,
            "llama3.1": 128000,
            "llama3": 8192,
            "llama2": 4096,
            "mistral": 32768,
            "mixtral": 32768,
            "phi3": 128000,
            "gemma": 8192,
            "deepseek-coder": 16384,
            "codellama": 16384,
            "qwen": 32768,
            "neural-chat": 8192,
        }
        
        # Try to match base model name
        for key, window in context_map.items():
            if model_name.lower().startswith(key):
                return window
        
        # Default to 4096 for unknown models
        return 4096
