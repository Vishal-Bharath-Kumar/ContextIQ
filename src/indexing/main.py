"""FastAPI application entry point for the ContextIQ Indexing service.

TASK-US027-04: Wires the IndexingConsumer (Kafka), IndexingPipeline
(embed -> Qdrant -> OpenSearch -> PostgreSQL), and DeletionHandler together
and runs the consume loop as a background asyncio task for the lifetime of
the process.

Entry point
-----------
::

    python -m src.indexing.main

or via uvicorn::

    uvicorn src.indexing.main:app --host 0.0.0.0 --port 8002
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from src.connector_sdk.registry import ConnectorRegistry
from src.data.database import primary_session_factory
from src.governance.opa.health import opa_health_status
from src.indexing.consumer import IndexingConsumer
from src.indexing.embedding.service import EmbeddingService
from src.indexing.pipeline import IndexingPipeline
from src.indexing.repositories.chunk_repository import ChunkRepository
from src.indexing.stores.deletion_handler import DeletionHandler
from src.indexing.stores.opensearch_indexer import OpenSearchIndexer
from src.indexing.stores.qdrant_indexer import QdrantIndexer

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Wire the pipeline/consumer, start the consume loop, and clean up on shutdown."""
    logger.warning("indexing: wiring pipeline dependencies")

    # A single AsyncSession is safe here because IndexingConsumer.run() processes
    # messages sequentially (one `await` at a time), never concurrently.
    session = primary_session_factory()()
    chunk_repo = ChunkRepository(session)
    qdrant = QdrantIndexer()
    opensearch = OpenSearchIndexer()
    embedder = EmbeddingService()
    registry = ConnectorRegistry()
    logger.warning("indexing: loading connector registry")
    await registry.load()
    logger.warning("indexing: connector registry loaded")

    pipeline = IndexingPipeline(
        embedder=embedder,
        qdrant=qdrant,
        opensearch=opensearch,
        chunk_repo=chunk_repo,
        registry=registry,
        # Enables lazily building a per-knowledge-source connector (from the
        # knowledge_sources table) the first time a source is synced, since
        # the entry-point registry.load() above only holds one shared,
        # unscoped instance per connector TYPE, not per source.
        session_factory=primary_session_factory(),
    )
    deletion_handler = DeletionHandler(
        chunk_repo=chunk_repo,
        qdrant=qdrant,
        opensearch=opensearch,
    )

    consumer = IndexingConsumer(pipeline, deletion_handler)
    await consumer.start()
    logger.warning("indexing: consumer started")
    app.state.consumer = consumer
    consume_task = asyncio.create_task(consumer.run())
    logger.warning("indexing: consume loop started")

    yield

    logger.warning("indexing: shutdown — stopping consumer")
    await consumer.stop()
    consume_task.cancel()
    try:
        await consume_task
    except asyncio.CancelledError:
        pass
    await pipeline.close()
    await session.close()
    logger.warning("indexing: shutdown complete")


def create_app() -> FastAPI:
    """Create and return the Indexing service FastAPI application."""
    application = FastAPI(
        title="ContextIQ Indexing",
        description="Consumes knowledge-source sync events and drives the embed/index pipeline.",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.get("/healthz")
    async def healthz() -> dict[str, object]:
        return {
            "status": "ok",
            "opa": opa_health_status(
                configured=False,
                bundle_ready=False,
                degraded=False,
            ),
        }

    return application


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "src.indexing.main:app",
        host="0.0.0.0",  # noqa: S104
        port=8002,
        log_level="info",
    )
