"""src.indexing.embedding — batch embedding sub-package."""
from src.indexing.embedding.fastembed_provider import FastEmbedProvider
from src.indexing.embedding.service import EmbeddingService, EmbeddingSettings

__all__ = ["EmbeddingService", "EmbeddingSettings", "FastEmbedProvider"]
