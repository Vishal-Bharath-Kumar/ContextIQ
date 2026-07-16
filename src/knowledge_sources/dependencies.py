"""FastAPI dependency provider for KnowledgeSourceService — TASK-US025-04."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.dependencies import get_db
from src.knowledge_sources.services.knowledge_source_service import KnowledgeSourceService
from src.knowledge_sources.vault_validator import VaultPathValidator


async def get_knowledge_source_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeSourceService:
    return KnowledgeSourceService(session=session, validator=VaultPathValidator())
