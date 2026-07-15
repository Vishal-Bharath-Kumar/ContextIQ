"""
Create the contextiq_embeddings Qdrant collection.
AC-1: 1536-dimensional vectors (text-embedding-3-small), cosine distance.
Run once after Qdrant cluster is healthy. Idempotent.

Usage:
    python scripts/datastore/bootstrap_qdrant.py
"""
from __future__ import annotations

import os
import sys

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    HnswConfigDiff,
    OptimizersConfigDiff,
    VectorParams,
)

QDRANT_URL     = os.environ.get("QDRANT_URL",     "http://qdrant.contextiq-data.svc.cluster.local:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
COLLECTION     = "contextiq_embeddings"


def main() -> int:
    client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY or None,
        timeout=30,
    )

    # Verify cluster health before attempting collection creation
    cluster_info = client.get_cluster_info()
    peer_count = len(cluster_info.peers) if cluster_info.peers else 0
    print(f"Qdrant cluster peers: {peer_count}")
    if peer_count < 3:
        print(f"WARNING: Expected 3 peers, got {peer_count}. Proceeding anyway.")

    # Idempotent: skip creation if collection already exists
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION in existing:
        print(f"Collection '{COLLECTION}' already exists — skipping creation.")
        info = client.get_collection(COLLECTION)
        print(f"  vectors_config: {info.config.params.vectors}")
        return 0

    print(f"Creating collection '{COLLECTION}'...")
    client.create_collection(
        collection_name=COLLECTION,
        # AC-1: text-embedding-3-small dimension = 1536, cosine distance
        # VectorParams is passed directly for an unnamed (default) vector space;
        # VectorsConfig is for named multi-vector spaces (not needed here).
        vectors_config=VectorParams(
            size=1536,
            distance=Distance.COSINE,
            on_disk=True,    # keep vectors on disk for large collections (memory efficiency)
        ),
        # AC-1: replication_factor=2 — each shard exists on 2 of the 3 nodes;
        #        tolerates 1 node failure without data loss
        replication_factor=2,
        write_consistency_factor=1,    # favour availability over strong write consistency
        hnsw_config=HnswConfigDiff(
            m=16,                        # HNSW M parameter — good default for 1536-d
            ef_construct=100,            # higher = better recall at index build time
            full_scan_threshold=10_000,  # use brute-force for result sets < 10k vectors
        ),
        optimizers_config=OptimizersConfigDiff(
            indexing_threshold=10_000,   # build HNSW index after 10k vectors in a segment
        ),
    )

    # Payload indexes for filtered vector search (source_id and chunk_index)
    client.create_payload_index(
        collection_name=COLLECTION,
        field_name="source_id",
        field_schema="keyword",
    )
    client.create_payload_index(
        collection_name=COLLECTION,
        field_name="chunk_index",
        field_schema="integer",
    )

    print(f"Collection '{COLLECTION}' created successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
