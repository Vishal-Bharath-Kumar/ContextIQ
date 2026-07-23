"""Unit tests for IndexingPipeline's lazy per-source connector loading.

Covers the fallback path added to ``run_for_source`` when
``self._registry.get(str(source_id))`` returns ``None``: build a connector
from the ``knowledge_sources`` table (the table the Admin Portal's Add
Connector wizard writes to), authenticate it, and register it for reuse.

All DB/connector-class lookups are patched; no live PostgreSQL or HTTP calls.
"""
from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.indexing.pipeline import IndexingPipeline
from src.indexing.schemas.chunk import ChunkPayload

SOURCE_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
TENANT_ID = "acme"

pytestmark = pytest.mark.asyncio


def _make_session_factory() -> tuple[MagicMock, MagicMock]:
    """Return (session_factory, session) where session_factory()() -> async context manager."""
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=session)
    return session_factory, session


def _make_record(connector_type: str = "github") -> SimpleNamespace:
    return SimpleNamespace(
        id=SOURCE_ID,
        connector_type=connector_type,
        credentials_vault_path="connectors/github/acme",
        scope="acme-org/api-service",
    )


@pytest.fixture
def make_chunk() -> Callable[..., ChunkPayload]:
    def _make() -> ChunkPayload:
        return ChunkPayload(
            source_id=SOURCE_ID,
            tenant_id=TENANT_ID,
            document_id="github:acme-org/api-service:sha1",
            text="hello",
            token_count=2,
        )

    return _make


def _build_pipeline(
    registry: MagicMock,
    session_factory: MagicMock,
    mock_qdrant: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_chunk_repo: AsyncMock,
    mock_embedder: AsyncMock,
) -> IndexingPipeline:
    return IndexingPipeline(
        embedder=mock_embedder,
        qdrant=mock_qdrant,
        opensearch=mock_opensearch,
        chunk_repo=mock_chunk_repo,
        registry=registry,
        session_factory=session_factory,
    )


class TestLazyLoadSuccess:
    async def test_builds_authenticates_and_registers_connector(
        self,
        mock_qdrant: AsyncMock,
        mock_opensearch: AsyncMock,
        mock_chunk_repo: AsyncMock,
        mock_embedder: AsyncMock,
        make_chunk: Callable[..., ChunkPayload],
    ) -> None:
        registry = MagicMock()
        registry.get = MagicMock(return_value=None)
        registry.register = MagicMock()
        session_factory, _session = _make_session_factory()

        connector_instance = AsyncMock()
        connector_instance.authenticate = AsyncMock()
        connector_instance.get_chunks = AsyncMock(return_value=[make_chunk()])
        connector_cls = MagicMock(return_value=connector_instance)
        config_cls = MagicMock()

        repo_instance = AsyncMock()
        repo_instance.get_by_id = AsyncMock(return_value=_make_record())

        pipeline = _build_pipeline(
            registry, session_factory, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_embedder
        )

        with (
            patch(
                "src.agents.retrieval.connector_loader.CONNECTOR_CLASS_MAP",
                {"github": (connector_cls, config_cls)},
            ),
            patch(
                "src.knowledge_sources.repositories.knowledge_source_repository.KnowledgeSourceRepository",
                return_value=repo_instance,
            ),
        ):
            count = await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

        config_cls.assert_called_once_with(
            vault_path="connectors/github/acme", repos=["acme-org/api-service"]
        )
        connector_instance.authenticate.assert_awaited_once()
        registry.register.assert_called_once_with(str(SOURCE_ID), connector_instance)
        connector_instance.get_chunks.assert_awaited_once_with(
            source_id=SOURCE_ID, tenant_id=TENANT_ID
        )
        assert count == 1

    async def test_reuses_existing_registry_entry_without_db_lookup(
        self,
        mock_qdrant: AsyncMock,
        mock_opensearch: AsyncMock,
        mock_chunk_repo: AsyncMock,
        mock_embedder: AsyncMock,
        make_chunk: Callable[..., ChunkPayload],
    ) -> None:
        """When the registry already has a connector, no DB lookup happens at all."""
        connector_instance = AsyncMock()
        connector_instance.get_chunks = AsyncMock(return_value=[make_chunk()])
        registry = MagicMock()
        registry.get = MagicMock(return_value=connector_instance)
        session_factory, _session = _make_session_factory()

        pipeline = _build_pipeline(
            registry, session_factory, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_embedder
        )

        with patch(
            "src.knowledge_sources.repositories.knowledge_source_repository.KnowledgeSourceRepository"
        ) as repo_cls:
            await pipeline.run_for_source(SOURCE_ID, TENANT_ID)
            repo_cls.assert_not_called()


class TestLazyLoadGracefulFailures:
    async def test_returns_zero_chunks_when_source_not_found(
        self,
        mock_qdrant: AsyncMock,
        mock_opensearch: AsyncMock,
        mock_chunk_repo: AsyncMock,
        mock_embedder: AsyncMock,
    ) -> None:
        registry = MagicMock()
        registry.get = MagicMock(return_value=None)
        session_factory, _session = _make_session_factory()
        mock_embedder.embed_batch = AsyncMock(return_value=[])

        repo_instance = AsyncMock()
        repo_instance.get_by_id = AsyncMock(return_value=None)

        pipeline = _build_pipeline(
            registry, session_factory, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_embedder
        )

        with patch(
            "src.knowledge_sources.repositories.knowledge_source_repository.KnowledgeSourceRepository",
            return_value=repo_instance,
        ):
            count = await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

        assert count == 0
        registry.register.assert_not_called()

    async def test_returns_zero_chunks_when_connector_type_unmapped(
        self,
        mock_qdrant: AsyncMock,
        mock_opensearch: AsyncMock,
        mock_chunk_repo: AsyncMock,
        mock_embedder: AsyncMock,
    ) -> None:
        registry = MagicMock()
        registry.get = MagicMock(return_value=None)
        session_factory, _session = _make_session_factory()
        mock_embedder.embed_batch = AsyncMock(return_value=[])

        repo_instance = AsyncMock()
        repo_instance.get_by_id = AsyncMock(return_value=_make_record(connector_type="unknown"))

        pipeline = _build_pipeline(
            registry, session_factory, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_embedder
        )

        with (
            patch("src.agents.retrieval.connector_loader.CONNECTOR_CLASS_MAP", {}),
            patch(
                "src.knowledge_sources.repositories.knowledge_source_repository.KnowledgeSourceRepository",
                return_value=repo_instance,
            ),
        ):
            count = await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

        assert count == 0

    async def test_returns_zero_chunks_when_authenticate_fails(
        self,
        mock_qdrant: AsyncMock,
        mock_opensearch: AsyncMock,
        mock_chunk_repo: AsyncMock,
        mock_embedder: AsyncMock,
    ) -> None:
        registry = MagicMock()
        registry.get = MagicMock(return_value=None)
        session_factory, _session = _make_session_factory()
        mock_embedder.embed_batch = AsyncMock(return_value=[])

        connector_instance = AsyncMock()
        connector_instance.authenticate = AsyncMock(side_effect=RuntimeError("vault down"))
        connector_cls = MagicMock(return_value=connector_instance)
        config_cls = MagicMock()

        repo_instance = AsyncMock()
        repo_instance.get_by_id = AsyncMock(return_value=_make_record())

        pipeline = _build_pipeline(
            registry, session_factory, mock_qdrant, mock_opensearch, mock_chunk_repo, mock_embedder
        )

        with (
            patch(
                "src.agents.retrieval.connector_loader.CONNECTOR_CLASS_MAP",
                {"github": (connector_cls, config_cls)},
            ),
            patch(
                "src.knowledge_sources.repositories.knowledge_source_repository.KnowledgeSourceRepository",
                return_value=repo_instance,
            ),
        ):
            count = await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

        assert count == 0
        registry.register.assert_not_called()

    async def test_no_lazy_load_attempted_without_session_factory(
        self,
        mock_qdrant: AsyncMock,
        mock_opensearch: AsyncMock,
        mock_chunk_repo: AsyncMock,
        mock_embedder: AsyncMock,
    ) -> None:
        """Backward compatible: no session_factory -> just treat missing connector as 0 chunks."""
        registry = MagicMock()
        registry.get = MagicMock(return_value=None)
        mock_embedder.embed_batch = AsyncMock(return_value=[])

        pipeline = IndexingPipeline(
            embedder=mock_embedder,
            qdrant=mock_qdrant,
            opensearch=mock_opensearch,
            chunk_repo=mock_chunk_repo,
            registry=registry,
        )

        count = await pipeline.run_for_source(SOURCE_ID, TENANT_ID)

        assert count == 0
