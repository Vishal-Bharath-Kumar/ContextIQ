"""Business logic for the Model Capability Registry lifecycle.

Provides CRUD operations for model definitions with a 409 duplicate guard
and Redis pub/sub invalidation after every mutation.

Pub/sub channel: contextiq:model_registry:changed

TASK-US018-03 — EP-006 Dynamic Model Routing
"""
from __future__ import annotations

import json
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.model_registry.repositories.model_repository import ModelRepository
from src.model_registry.schemas.model_definition import (
    LatencyTier,
    ModelCapability,
    ModelDefinition,
    ModelRegistration,
)
from src.model_registry.schemas.model_installation import (
    ModelInstallationRequest,
    ModelInstallationResponse,
    OllamaPullRequest,
)
from src.model_registry.services.model_credential_service import ModelCredentialService
from src.model_registry.services.ollama_service import OllamaService

REGISTRY_CHANGE_CHANNEL = "contextiq:model_registry:changed"  # mirrors tool registry pattern


class ModelRegistryService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        credential_service: Optional[ModelCredentialService] = None,
        ollama_service: Optional[OllamaService] = None,
    ) -> None:
        self._session = session
        self._repo = ModelRepository(session)
        self._redis = redis
        self._credential_service = credential_service or ModelCredentialService()
        self._ollama_service = ollama_service or OllamaService()

    async def register(self, registration: ModelRegistration) -> ModelDefinition:
        existing = await self._repo.get_by_model_id(registration.model_id)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Model '{registration.model_id}' is already registered.",
            )
        record = await self._repo.create(registration)
        await self._session.commit()
        await self._publish_change_event(registration.model_id)
        return ModelDefinition.model_validate(record)

    async def list_active(self) -> list[ModelDefinition]:
        records = await self._repo.list_active()
        return [ModelDefinition.model_validate(r) for r in records]
    
    async def list_all(self) -> list[ModelDefinition]:
        """Return all models regardless of active status."""
        records = await self._repo.list_all()
        return [ModelDefinition.model_validate(r) for r in records]

    async def set_active(self, model_id: UUID, is_active: bool) -> ModelDefinition:
        record = await self._repo.set_active(model_id, is_active)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found.")
        await self._session.commit()
        await self._publish_change_event(record.model_id)
        return ModelDefinition.model_validate(record)

    async def _publish_change_event(self, model_id: str) -> None:
        payload = json.dumps({"event": "model_registered", "model_id": model_id})
        await self._redis.publish(REGISTRY_CHANGE_CHANNEL, payload)
    
    async def install_model(
        self,
        request: ModelInstallationRequest,
    ) -> ModelInstallationResponse:
        """Install a new model with credentials (API-based or Ollama)."""
        
        if request.provider_type == "ollama":
            return await self._install_ollama_model(request)
        else:
            return await self._install_api_model(request)
    
    async def _install_ollama_model(
        self,
        request: ModelInstallationRequest,
    ) -> ModelInstallationResponse:
        """Install an Ollama model (pull if needed)."""
        
        model_name = request.ollama_model_name or request.model_id.replace("ollama/", "")
        
        # Check if model exists, pull if needed
        exists = await self._ollama_service.check_model_exists(model_name)
        
        if not exists and request.auto_pull:
            pull_request = OllamaPullRequest(model_name=model_name)
            pull_response = await self._ollama_service.pull_model(pull_request)
            
            if pull_response.status != "success":
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to pull Ollama model: {pull_response.message}"
                )
        elif not exists:
            raise HTTPException(
                status_code=404,
                detail=f"Ollama model '{model_name}' not found. Enable auto_pull to download it."
            )
        
        # Get model info and estimate context window
        context_window = await self._ollama_service.estimate_context_window(model_name)
        
        # Register the model
        model_id = f"ollama/{model_name}" if not request.model_id.startswith("ollama/") else request.model_id
        
        registration = ModelRegistration(
            model_id=model_id,
            provider="ollama",
            context_window=request.context_window or context_window,
            cost_per_1k_tokens=0.0,  # Ollama is free
            latency_tier=LatencyTier.MEDIUM,
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.COMPLETION,
                ModelCapability.CODE,
            ],
            is_active=True,
        )
        
        await self.register(registration)
        
        return ModelInstallationResponse(
            model_id=model_id,
            provider_type="ollama",
            status="installed",
            message=f"Ollama model '{model_name}' installed and registered successfully",
            credentials_stored=False,
        )
    
    async def _install_api_model(
        self,
        request: ModelInstallationRequest,
    ) -> ModelInstallationResponse:
        """Install an API-based model (OpenAI, Anthropic, etc.) with credentials."""
        
        # Validate required fields
        if not request.api_key:
            raise HTTPException(
                status_code=400,
                detail="API key is required for API-based model providers"
            )
        
        if not request.context_window:
            raise HTTPException(
                status_code=400,
                detail="Context window is required for API-based models"
            )
        
        # Store credentials in Vault
        credentials = {
            "api_key": request.api_key,
            "api_base": request.api_base,
            "api_version": request.api_version,
            "deployment_name": request.deployment_name,
        }
        
        # Remove None values
        credentials = {k: v for k, v in credentials.items() if v is not None}
        
        credentials_stored = await self._credential_service.store_credentials(
            model_id=request.model_id,
            provider_type=request.provider_type.value,
            credentials=credentials,
        )
        
        # Determine provider name
        provider_map = {
            "openai": "openai",
            "anthropic": "anthropic",
            "google": "google",
            "azure_openai": "azure",
            "huggingface": "huggingface",
        }
        provider = provider_map.get(request.provider_type.value, request.provider_type.value)
        
        # Auto-detect capabilities based on provider and model name
        capabilities = self._detect_capabilities(request.model_id, request.provider_type.value)
        
        # Auto-detect latency tier
        latency_tier = self._detect_latency_tier(request.model_id)
        
        # Register the model
        registration = ModelRegistration(
            model_id=request.model_id,
            provider=provider,
            context_window=request.context_window,
            cost_per_1k_tokens=request.cost_per_1k_tokens or 0.0,
            latency_tier=latency_tier,
            capabilities=capabilities,
            is_active=True,
        )
        
        await self.register(registration)
        
        return ModelInstallationResponse(
            model_id=request.model_id,
            provider_type=request.provider_type.value,
            status="installed",
            message=f"Model '{request.model_id}' installed and registered successfully",
            credentials_stored=credentials_stored,
        )
    
    def _detect_capabilities(
        self,
        model_id: str,
        provider_type: str,
    ) -> list[ModelCapability]:
        """Auto-detect model capabilities based on model ID and provider."""
        
        capabilities = [ModelCapability.CHAT, ModelCapability.COMPLETION]
        
        # Code-specific models
        if any(keyword in model_id.lower() for keyword in ["code", "coder", "codex"]):
            capabilities.append(ModelCapability.CODE)
        
        # Vision models
        if any(keyword in model_id.lower() for keyword in ["vision", "gpt-4o", "claude-3"]):
            capabilities.append(ModelCapability.VISION)
        
        # Function calling
        if provider_type in ["openai", "anthropic", "google"]:
            capabilities.append(ModelCapability.FUNCTION_CALL)
        
        # Embedding models
        if "embed" in model_id.lower():
            capabilities = [ModelCapability.EMBEDDING]
        
        return capabilities
    
    def _detect_latency_tier(self, model_id: str) -> LatencyTier:
        """Auto-detect latency tier based on model ID."""
        
        model_lower = model_id.lower()
        
        # Fast models
        if any(keyword in model_lower for keyword in ["mini", "haiku", "flash", "turbo"]):
            return LatencyTier.FAST
        
        # Slow models (reasoning/o1)
        if any(keyword in model_lower for keyword in ["o1", "reasoning", "think"]):
            return LatencyTier.SLOW
        
        # Default to medium
        return LatencyTier.MEDIUM
    
    async def delete_model(
        self,
        model_id: UUID,
        delete_from_ollama: bool = False,
    ) -> dict[str, str]:
        """Delete a model from the registry and optionally from Ollama."""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[SERVICE] delete_model called for {model_id}")
        
        # Get the model record
        record = await self._repo.get_by_id(model_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"Model '{model_id}' not found."
            )
        
        logger.info(f"[SERVICE] Found model: {record.model_id} (provider={record.provider})")
        
        # Store model info before deletion
        model_info = {
            "model_id": record.model_id,
            "provider": record.provider,
        }
        
        # If it's an Ollama model and delete_from_ollama is True, delete from Ollama
        if record.provider == "ollama" and delete_from_ollama:
            model_name = record.model_id.replace("ollama/", "")
            logger.info(f"[SERVICE] Deleting from Ollama: {model_name}")
            await self._ollama_service.delete_model(model_name)
        
        # Delete the model record from database
        logger.info(f"[SERVICE] Calling session.delete() on record id={record.id}")
        await self._session.delete(record)
        logger.info("[SERVICE] session.delete() completed, deletion staged")
        # Note: Don't commit here - let the caller commit after audit logging
        
        return {
            "status": "deleted",
            "message": f"Model '{record.model_id}' deleted successfully",
            **model_info,  # Include model_id and provider for audit logging
        }

