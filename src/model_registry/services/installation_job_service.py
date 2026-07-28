"""Background job service for async model installations.

Handles long-running model downloads and installations in background tasks,
providing progress tracking and status updates.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.database import primary_session_factory
from src.data.dependencies import get_redis_client
from src.model_registry.models.installation_job import ModelInstallationJob
from src.model_registry.schemas.model_installation import (
    InstallationJobProgress,
    InstallationJobResponse,
    InstallationJobStatus,
    ModelInstallationRequest,
)
from src.model_registry.services.ollama_service import OllamaService

logger = logging.getLogger(__name__)


class ModelInstallationJobService:
    """Service for managing background model installation jobs."""

    def __init__(self) -> None:
        self._ollama_service = OllamaService()
        self._active_tasks: dict[UUID, asyncio.Task] = {}

    async def create_job(
        self,
        request: ModelInstallationRequest,
        created_by: str | None = None,
    ) -> InstallationJobResponse:
        """Create a new installation job and start it in the background."""
        async with primary_session_factory()() as session:
            # Create job record
            job = ModelInstallationJob(
                model_id=request.model_id,
                provider_type=request.provider_type.value,
                status=InstallationJobStatus.PENDING.value,
                request_params=request.model_dump(),
                created_by=created_by,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        # Start background task
        task = asyncio.create_task(self._run_installation(job_id, request))
        self._active_tasks[job_id] = task
        
        # Clean up task when done
        task.add_done_callback(lambda _: self._active_tasks.pop(job_id, None))

        return InstallationJobResponse(
            job_id=job_id,
            model_id=request.model_id,
            provider_type=request.provider_type.value,
            status=InstallationJobStatus.PENDING,
            message=f"Installation job created for {request.model_id}",
        )

    async def get_job_status(
        self,
        job_id: UUID,
        session: AsyncSession,
    ) -> InstallationJobProgress | None:
        """Get the current status of an installation job."""
        stmt = select(ModelInstallationJob).where(ModelInstallationJob.id == job_id)
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        
        if not job:
            return None

        return InstallationJobProgress(
            job_id=job.id,
            model_id=job.model_id,
            provider_type=job.provider_type,
            status=InstallationJobStatus(job.status),
            progress_pct=job.progress_pct,
            current_step=job.current_step,
            error_message=job.error_message,
            started_at=job.started_at,
            completed_at=job.completed_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    async def list_jobs(
        self,
        session: AsyncSession,
        limit: int = 50,
    ) -> list[InstallationJobProgress]:
        """List recent installation jobs."""
        stmt = (
            select(ModelInstallationJob)
            .order_by(ModelInstallationJob.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        jobs = result.scalars().all()

        return [
            InstallationJobProgress(
                job_id=job.id,
                model_id=job.model_id,
                provider_type=job.provider_type,
                status=InstallationJobStatus(job.status),
                progress_pct=job.progress_pct,
                current_step=job.current_step,
                error_message=job.error_message,
                started_at=job.started_at,
                completed_at=job.completed_at,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
            for job in jobs
        ]

    async def _run_installation(
        self,
        job_id: UUID,
        request: ModelInstallationRequest,
    ) -> None:
        """Execute the model installation in the background."""
        try:
            # Update job to running
            await self._update_job_status(
                job_id,
                status=InstallationJobStatus.RUNNING,
                progress_pct=0.0,
                current_step="Starting installation...",
                started_at=datetime.utcnow(),
            )

            if request.provider_type == "ollama":
                await self._install_ollama(job_id, request)
            else:
                await self._install_api_model(job_id, request)

            # Mark as completed
            await self._update_job_status(
                job_id,
                status=InstallationJobStatus.COMPLETED,
                progress_pct=100.0,
                current_step="Installation completed",
                completed_at=datetime.utcnow(),
            )
            
            logger.info(f"Installation job {job_id} completed successfully")

        except Exception as e:
            logger.exception(f"Installation job {job_id} failed: {e}")
            await self._update_job_status(
                job_id,
                status=InstallationJobStatus.FAILED,
                error_message=str(e),
                current_step="Installation failed",
                completed_at=datetime.utcnow(),
            )

    async def _install_ollama(
        self,
        job_id: UUID,
        request: ModelInstallationRequest,
    ) -> None:
        """Install an Ollama model with progress tracking."""
        model_name = request.ollama_model_name or request.model_id.replace("ollama/", "")
        
        # Check if model exists
        await self._update_job_status(
            job_id,
            progress_pct=10.0,
            current_step=f"Checking if '{model_name}' exists...",
        )
        
        exists = await self._ollama_service.check_model_exists(model_name)
        
        if not exists:
            if not request.auto_pull:
                raise ValueError(
                    f"Ollama model '{model_name}' not found. "
                    "Enable auto_pull to download it."
                )
            
            # Pull the model
            await self._update_job_status(
                job_id,
                progress_pct=20.0,
                current_step=f"Downloading '{model_name}'...",
            )
            
            from src.model_registry.schemas.model_installation import OllamaPullRequest
            pull_request = OllamaPullRequest(model_name=model_name)
            pull_response = await self._ollama_service.pull_model(pull_request)
            
            if pull_response.status != "success":
                raise ValueError(f"Failed to pull model: {pull_response.message}")
            
            await self._update_job_status(
                job_id,
                progress_pct=70.0,
                current_step="Download completed",
            )
        else:
            await self._update_job_status(
                job_id,
                progress_pct=60.0,
                current_step="Model already downloaded",
            )
        
        # Get model info
        await self._update_job_status(
            job_id,
            progress_pct=80.0,
            current_step="Detecting context window...",
        )
        
        context_window = await self._ollama_service.estimate_context_window(model_name)
        
        # Register the model
        await self._update_job_status(
            job_id,
            progress_pct=90.0,
            current_step="Registering model...",
        )
        
        model_id = f"ollama/{model_name}" if not request.model_id.startswith("ollama/") else request.model_id
        
        from src.model_registry.schemas.model_definition import (
            LatencyTier,
            ModelCapability,
            ModelRegistration,
        )
        
        registration = ModelRegistration(
            model_id=model_id,
            provider="ollama",
            context_window=request.context_window or context_window,
            cost_per_1k_tokens=0.0,
            latency_tier=LatencyTier.MEDIUM,
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.COMPLETION,
                ModelCapability.CODE,
            ],
            is_active=True,
        )
        
        # Register the model using a fresh session and redis client
        async with primary_session_factory()() as reg_session:
            redis = get_redis_client()
            from src.model_registry.services.model_registry_service import ModelRegistryService
            registry_service = ModelRegistryService(
                session=reg_session,
                redis=redis,
            )
            await registry_service.register(registration)
            await reg_session.commit()

    async def _install_api_model(
        self,
        job_id: UUID,
        request: ModelInstallationRequest,
    ) -> None:
        """Install an API-based model."""
        await self._update_job_status(
            job_id,
            progress_pct=50.0,
            current_step="Installing API-based model...",
        )
        
        # Create registry service with proper dependencies
        async with primary_session_factory()() as reg_session:
            redis = get_redis_client()
            from src.model_registry.services.model_registry_service import ModelRegistryService
            registry_service = ModelRegistryService(
                session=reg_session,
                redis=redis,
            )
            await registry_service._install_api_model(request)
            await reg_session.commit()

    async def _update_job_status(
        self,
        job_id: UUID,
        status: InstallationJobStatus | None = None,
        progress_pct: float | None = None,
        current_step: str | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        """Update job status in the database."""
        async with primary_session_factory()() as session:
            stmt = select(ModelInstallationJob).where(ModelInstallationJob.id == job_id)
            result = await session.execute(stmt)
            job = result.scalar_one_or_none()
            
            if not job:
                logger.error(f"Job {job_id} not found for status update")
                return
            
            if status is not None:
                job.status = status.value
            if progress_pct is not None:
                job.progress_pct = progress_pct
            if current_step is not None:
                job.current_step = current_step
            if error_message is not None:
                job.error_message = error_message
            if started_at is not None:
                job.started_at = started_at
            if completed_at is not None:
                job.completed_at = completed_at
            
            job.updated_at = datetime.utcnow()
            
            await session.commit()
