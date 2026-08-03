"""OpenSearchIndexer — async BM25 bulk indexing and deletion for the EP-008 pipeline.

TASK-US027-03: Implements keyword storage into per-tenant OpenSearch indices
using the naming scheme ``contextiq_chunks_{tenant_id}``.
"""
from __future__ import annotations

from opensearchpy import AsyncOpenSearch, helpers
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.indexing.schemas.chunk import IndexedChunk


class OpenSearchSettings(BaseSettings):
    """OpenSearch connection settings sourced from environment variables."""

    model_config = SettingsConfigDict(env_prefix="OPENSEARCH_", env_file=".env")

    url: str = "http://localhost:9200"
    username: str = "admin"
    password: str = "admin"  # noqa: S105 — default overridden via OPENSEARCH_PASSWORD env var
    bulk_size: int = 256
    # Index naming: contextiq_chunks_{tenant_id}
    index_prefix: str = "contextiq_chunks"


def index_name(tenant_id: str) -> str:
    """Return the OpenSearch index name for a given tenant."""
    return f"contextiq_chunks_{tenant_id}"


class OpenSearchIndexer:
    """Async adapter for bulk indexing and deleting documents in OpenSearch."""

    def __init__(self, settings: OpenSearchSettings | None = None) -> None:
        self._settings = settings or OpenSearchSettings()
        self._client = AsyncOpenSearch(
            hosts=[self._settings.url],
            http_auth=(self._settings.username, self._settings.password),
            use_ssl=self._settings.url.startswith("https"),
            verify_certs=False,  # override in production via settings
        )

    async def ensure_index(self, tenant_id: str) -> None:
        """Create the index with BM25 mappings if it does not already exist."""
        name = index_name(tenant_id)
        if not await self._client.indices.exists(index=name):
            await self._client.indices.create(
                index=name,
                body={
                    "mappings": {
                        "properties": {
                            "chunk_id": {"type": "keyword"},
                            "source_id": {"type": "keyword"},
                            "document_id": {"type": "keyword"},
                            "text": {"type": "text", "analyzer": "english"},
                            "metadata": {"type": "object", "dynamic": True},
                        }
                    }
                },
            )

    async def bulk_index(self, chunks: list[IndexedChunk], tenant_id: str) -> None:
        """Bulk index chunk text and metadata for BM25 search."""
        name = index_name(tenant_id)
        actions = [
            {
                "_index": name,
                "_id": str(c.payload.chunk_id),
                "_source": {
                    "chunk_id": str(c.payload.chunk_id),
                    "source_id": str(c.payload.source_id),
                    "document_id": c.payload.document_id,
                    "text": c.payload.text,
                    "metadata": c.payload.metadata,
                },
            }
            for c in chunks
        ]
        await helpers.async_bulk(self._client, actions)

    async def delete_by_document(self, document_id: str, tenant_id: str) -> None:
        """Delete all entries for a given document_id (AC-7)."""
        name = index_name(tenant_id)
        await self._client.delete_by_query(
            index=name,
            body={"query": {"term": {"document_id": document_id}}},
        )

    async def close(self) -> None:
        """Close the underlying async HTTP client/session."""
        await self._client.close()
