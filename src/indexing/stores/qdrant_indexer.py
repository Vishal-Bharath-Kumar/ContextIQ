"""QdrantIndexer — async vector upsert and deletion for the EP-008 indexing pipeline.

TASK-US027-03: Implements vector storage into per-source Qdrant collections
using the naming scheme ``{source_id_hex}_{tenant_id}``.
"""
from __future__ import annotations

from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    Distance,
    PointStruct,
    UpdateStatus,
    VectorParams,
)

from src.indexing.schemas.chunk import IndexedChunk


class QdrantSettings(BaseSettings):
    """Qdrant connection and collection settings sourced from environment variables."""

    model_config = SettingsConfigDict(env_prefix="QDRANT_", env_file=".env")

    url: str = "http://localhost:6333"
    api_key: str | None = None
    # Vector dimension — must match the embedding model output.
    # text-embedding-3-small=1536, BAAI/bge-small-en-v1.5=384
    vector_size: int = 1536
    # Qdrant batch upsert limit per call.
    batch_size: int = 128
    distance: str = "Cosine"  # "Cosine" | "Dot" | "Euclid"


def collection_name(source_id: UUID, tenant_id: str) -> str:
    """Return the Qdrant collection name for a given source and tenant.

    Format: ``<source_id_hex_no_dashes>_<tenant_id>``
    Qdrant collection names must match ``[a-zA-Z0-9_-]+``.
    """
    return f"{source_id.hex}_{tenant_id}"


class QdrantIndexer:
    """Async adapter for upserting and deleting vector points in Qdrant."""

    def __init__(self, settings: QdrantSettings | None = None) -> None:
        self._settings = settings or QdrantSettings()
        self._client = AsyncQdrantClient(
            url=self._settings.url,
            api_key=self._settings.api_key,
        )

    async def ensure_collection(self, source_id: UUID, tenant_id: str) -> None:
        """Create the collection if it does not already exist. Idempotent."""
        name = collection_name(source_id, tenant_id)
        exists = await self._client.collection_exists(name)
        if not exists:
            await self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=self._settings.vector_size,
                    distance=Distance(self._settings.distance),
                ),
            )

    async def upsert(
        self,
        chunks: list[IndexedChunk],
        source_id: UUID,
        tenant_id: str,
    ) -> None:
        """Upsert all indexed chunks into the Qdrant collection in batches.

        Point ID is the chunk_id UUID (Qdrant natively supports UUID point IDs).
        Splits ``chunks`` into batches of ``settings.batch_size`` and upserts
        each batch sequentially, waiting for acknowledgement before continuing.
        """
        name = collection_name(source_id, tenant_id)
        batches = [
            chunks[i : i + self._settings.batch_size]
            for i in range(0, len(chunks), self._settings.batch_size)
        ]
        for batch in batches:
            points = [
                PointStruct(
                    id=str(c.payload.chunk_id),
                    vector=c.vector,
                    payload={
                        "source_id": str(c.payload.source_id),
                        "tenant_id": c.payload.tenant_id,
                        "document_id": c.payload.document_id,
                        "text": c.payload.text,
                        **c.payload.metadata,
                    },
                )
                for c in batch
            ]
            result = await self._client.upsert(
                collection_name=name,
                points=points,
                wait=True,
            )
            if result.status != UpdateStatus.COMPLETED:
                raise RuntimeError(
                    f"Qdrant upsert returned unexpected status: {result.status}"
                )

    async def delete_by_document(
        self,
        document_id: str,
        source_id: UUID,
        tenant_id: str,
        chunk_ids: list[UUID],
    ) -> None:
        """Delete all point IDs for a given document (stale embedding cleanup, AC-7)."""
        if not chunk_ids:
            return
        name = collection_name(source_id, tenant_id)
        await self._client.delete(
            collection_name=name,
            points_selector=[str(cid) for cid in chunk_ids],
            wait=True,
        )

    async def close(self) -> None:
        """Close the underlying async HTTP client/session."""
        await self._client.close()
