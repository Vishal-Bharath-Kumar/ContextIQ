"""Pydantic schemas for model installation requests.

Handles both API-based providers (OpenAI, Anthropic, etc.) requiring credentials
and local providers (Ollama) requiring model pull/download.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ModelProviderType(StrEnum):
    """Classification of model provider types for installation flow."""
    
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    AZURE_OPENAI = "azure_openai"
    OLLAMA = "ollama"
    HUGGINGFACE = "huggingface"
    CUSTOM = "custom"


class ModelInstallationRequest(BaseModel):
    """Request payload for installing a new model with credentials."""
    
    model_id: str = Field(
        min_length=1,
        max_length=128,
        description="Model identifier (e.g., 'gpt-4o-mini', 'ollama/llama3.2')",
    )
    provider_type: ModelProviderType
    display_name: str = Field(
        min_length=1,
        max_length=128,
        description="Human-readable name for the model",
    )
    
    # Provider credentials (for API-based providers)
    api_key: Optional[str] = Field(
        default=None,
        description="API key for the model provider (stored in Vault)",
    )
    api_base: Optional[str] = Field(
        default=None,
        description="Custom API base URL (for Azure or self-hosted)",
    )
    api_version: Optional[str] = Field(
        default=None,
        description="API version (primarily for Azure)",
    )
    deployment_name: Optional[str] = Field(
        default=None,
        description="Deployment name (for Azure OpenAI)",
    )
    
    # Model metadata (auto-detected for Ollama, required for API providers)
    context_window: Optional[int] = Field(
        default=None,
        gt=0,
        description="Max tokens in context window (auto-detected for Ollama)",
    )
    cost_per_1k_tokens: Optional[float] = Field(
        default=0.0,
        ge=0.0,
        description="USD per 1,000 tokens (0 for local/Ollama)",
    )
    
    # Ollama-specific
    ollama_model_name: Optional[str] = Field(
        default=None,
        description="Ollama model name for pulling (e.g., 'llama3.2', 'mistral')",
    )
    auto_pull: bool = Field(
        default=False,
        description="Automatically pull Ollama model if not available",
    )


class OllamaModelInfo(BaseModel):
    """Information about an available Ollama model."""
    
    name: str
    size: int
    digest: str
    modified_at: str


class OllamaPullRequest(BaseModel):
    """Request to pull/download an Ollama model."""
    
    model_name: str = Field(
        min_length=1,
        description="Ollama model name (e.g., 'llama3.2', 'mistral:7b')",
    )


class OllamaPullResponse(BaseModel):
    """Response from Ollama model pull operation."""
    
    status: str
    model_name: str
    message: str
    digest: Optional[str] = None


class ModelInstallationResponse(BaseModel):
    """Response after successful model installation."""
    
    model_id: str
    provider_type: str
    status: str  # "installed", "pulled", "registered"
    message: str
    credentials_stored: bool = False


class InstallationJobStatus(StrEnum):
    """Status of a background model installation job."""
    
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class InstallationJobResponse(BaseModel):
    """Response when creating a new installation job."""
    
    job_id: UUID
    model_id: str
    provider_type: str
    status: InstallationJobStatus
    message: str


class InstallationJobProgress(BaseModel):
    """Current progress of an installation job."""
    
    job_id: UUID
    model_id: str
    provider_type: str
    status: InstallationJobStatus
    progress_pct: float = Field(ge=0.0, le=100.0)
    current_step: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
