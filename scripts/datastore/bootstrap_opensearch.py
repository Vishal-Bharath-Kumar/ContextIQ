"""
AC-3: Create the contextiq_documents OpenSearch index with BM25 analyzer
and explicit field mappings.
Idempotent — skips creation if index already exists.

Usage:
    python scripts/datastore/bootstrap_opensearch.py
"""
from __future__ import annotations

import os
import sys
from typing import Any

from opensearchpy import OpenSearch, RequestError

OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "opensearch.contextiq-data.svc.cluster.local")
OPENSEARCH_PORT = int(os.environ.get("OPENSEARCH_PORT", "9200"))
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS = os.environ.get("OPENSEARCH_PASSWORD", "")
INDEX_NAME      = "contextiq_documents"

REQUIRED_FIELDS = ("content", "source_id", "metadata", "indexed_at")


def main() -> int:
    if not OPENSEARCH_PASS:
        print("ERROR: OPENSEARCH_PASSWORD not set", flush=True)
        return 1

    client = OpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        http_auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
        use_ssl=True,
        verify_certs=True,
        ssl_show_warn=False,
    )

    # Verify cluster health before creating index
    health: dict[str, Any] = client.cluster.health(wait_for_status="green", timeout="60s")
    print(f"Cluster health: {health['status']} — nodes: {health['number_of_nodes']}")
    if health["number_of_nodes"] < 3:
        print(f"WARNING: Expected 3 nodes, got {health['number_of_nodes']}")

    # Idempotent: skip creation if index already exists
    if client.indices.exists(index=INDEX_NAME):
        print(f"Index '{INDEX_NAME}' already exists — skipping creation.")
        mapping: dict[str, Any] = client.indices.get_mapping(index=INDEX_NAME)
        fields = list(mapping[INDEX_NAME]["mappings"]["properties"].keys())
        print(f"  Current fields: {fields}")
        return 0

    # AC-3: index settings — BM25 similarity + custom analyzer
    index_body: dict[str, Any] = {
        "settings": {
            "number_of_shards":   3,    # one primary shard per node
            "number_of_replicas": 1,    # one replica per shard — tolerates 1 node failure
            "similarity": {
                "default": {
                    "type": "BM25",
                    "b":    0.75,
                    "k1":   1.2,
                }
            },
            "analysis": {
                "analyzer": {
                    # AC-3: BM25-tuned analyzer for full-text content fields
                    "contextiq_bm25": {
                        "type":      "custom",
                        "tokenizer": "standard",
                        "filter": [
                            "lowercase",
                            "stop",
                            "porter_stem",
                            "contextiq_length_filter",
                        ],
                    },
                },
                "filter": {
                    "contextiq_length_filter": {
                        "type": "length",
                        "min":  2,
                        "max":  40,
                    }
                },
            },
        },
        "mappings": {
            # AC-3: explicit field mappings
            "properties": {
                "content": {
                    "type":     "text",
                    "analyzer": "contextiq_bm25",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 256}
                    },
                },
                # keyword fields store values as-is — no analyzer applies
                "source_id": {
                    "type": "keyword",
                },
                "metadata": {
                    "type":    "object",
                    "dynamic": True,    # allow arbitrary metadata sub-fields
                },
                "indexed_at": {
                    "type":   "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                # Supporting fields used by the agent retrieval pipeline
                "title": {
                    "type":     "text",
                    "analyzer": "contextiq_bm25",
                },
                "chunk_index": {
                    "type": "integer",
                },
                "connector_type": {
                    "type": "keyword",
                },
            }
        },
    }

    print(f"Creating index '{INDEX_NAME}'...")
    try:
        client.indices.create(index=INDEX_NAME, body=index_body)
    except RequestError as exc:
        if "resource_already_exists_exception" in str(exc):
            print(f"Index '{INDEX_NAME}' already exists (race condition) — OK.")
        else:
            print(f"ERROR creating index: {exc}", flush=True)
            return 1

    # Verify the index is green and all required fields are present
    idx_health: dict[str, Any] = client.cluster.health(
        index=INDEX_NAME, wait_for_status="green", timeout="30s"
    )
    print(f"Index '{INDEX_NAME}' created. Status: {idx_health['status']}")

    mapping = client.indices.get_mapping(index=INDEX_NAME)
    fields = list(mapping[INDEX_NAME]["mappings"]["properties"].keys())
    missing = [f for f in REQUIRED_FIELDS if f not in fields]
    if missing:
        print(f"ERROR: Required fields missing from mapping: {missing}", flush=True)
        return 1

    for field in REQUIRED_FIELDS:
        print(f"  [OK] field '{field}' present")

    return 0


if __name__ == "__main__":
    sys.exit(main())
