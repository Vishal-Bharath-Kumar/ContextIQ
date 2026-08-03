"""
Integration tests for US-051: Polyglot data store deployment.

Prerequisites:
  - All stores running and accessible from within cluster (or via port-forward)
  - Environment vars: QDRANT_URL, NEO4J_URI, NEO4J_PASSWORD, OPENSEARCH_HOST,
    OPENSEARCH_PASSWORD, REDIS_SENTINEL_HOSTS, REDIS_PASSWORD,
    MINIO_ENDPOINT, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD

Run:
    pytest tests/integration/test_datastores.py -v --tb=short
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest
import redis.asyncio as aioredis
from neo4j import GraphDatabase
from opensearchpy import OpenSearch
from qdrant_client import QdrantClient
from redis.asyncio.sentinel import Sentinel


# ---------------------------------------------------------------------------
# AC-1: Qdrant cluster + contextiq_embeddings collection
# ---------------------------------------------------------------------------

class TestAC1_Qdrant:

    def test_qdrant_cluster_has_3_peers(self) -> None:
        client = QdrantClient(
            url=os.environ.get("QDRANT_URL", "http://qdrant.contextiq-data.svc.cluster.local:6333"),
            api_key=os.environ.get("QDRANT_API_KEY"),
            timeout=30,
        )
        info = client.get_cluster_info()
        peer_count = len(info.peers) if info.peers else 0
        assert peer_count == 3, f"Expected 3 Qdrant peers, got {peer_count}"

    def test_contextiq_embeddings_collection_exists(self) -> None:
        client = QdrantClient(
            url=os.environ.get("QDRANT_URL", "http://qdrant.contextiq-data.svc.cluster.local:6333"),
            api_key=os.environ.get("QDRANT_API_KEY"),
        )
        info = client.get_collection("contextiq_embeddings")
        from qdrant_client.http.models import Distance
        assert info.config.params.vectors.size == 1536, (
            f"Expected 1536 dimensions, got {info.config.params.vectors.size}"
        )
        assert info.config.params.vectors.distance == Distance.COSINE, (
            "Expected COSINE distance metric"
        )

    def test_qdrant_vector_upsert_and_search(self) -> None:
        from qdrant_client.http.models import Distance, PointIdsList, PointStruct

        client = QdrantClient(
            url=os.environ.get("QDRANT_URL", "http://qdrant.contextiq-data.svc.cluster.local:6333"),
            api_key=os.environ.get("QDRANT_API_KEY"),
        )
        client.upsert(
            collection_name="contextiq_embeddings",
            points=[PointStruct(id=999999, vector=[0.1] * 1536, payload={"source_id": "test"})],
        )
        results = client.search(
            collection_name="contextiq_embeddings",
            query_vector=[0.1] * 1536,
            limit=1,
        )
        assert results, "Qdrant search returned no results after upsert"
        # Use PointIdsList to satisfy qdrant-client >= 1.9 type requirements
        client.delete(
            collection_name="contextiq_embeddings",
            points_selector=PointIdsList(points=[999999]),
        )


# ---------------------------------------------------------------------------
# AC-2: Neo4j cluster + schema constraints
# ---------------------------------------------------------------------------

class TestAC2_Neo4j:

    @pytest.fixture(scope="class")
    def neo4j_driver(self):
        d = GraphDatabase.driver(
            os.environ.get(
                "NEO4J_URI",
                "bolt://contextiq-neo4j.contextiq-data.svc.cluster.local:7687",
            ),
            auth=("neo4j", os.environ["NEO4J_PASSWORD"]),
        )
        yield d
        d.close()

    def test_neo4j_cluster_has_3_cores(self, neo4j_driver) -> None:
        with neo4j_driver.session() as s:
            result = s.run("CALL dbms.cluster.overview() YIELD role").data()
        roles = [r["role"] for r in result]
        assert len(roles) == 3, f"Expected 3 cluster members, got {len(roles)}: {roles}"

    def test_neo4j_constraints_exist(self, neo4j_driver) -> None:
        with neo4j_driver.session() as s:
            constraints = {r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name").data()}
        for expected in (
            "constraint_service_id",
            "constraint_repo_id",
            "constraint_developer_id",
            "constraint_incident_id",
        ):
            assert expected in constraints, f"Constraint {expected!r} missing"

    def test_neo4j_unique_constraint_enforced(self, neo4j_driver) -> None:
        with neo4j_driver.session() as s:
            s.run("MERGE (:Service {id: 'test-svc-1', name: 'test', namespace: 'default'})")
            with pytest.raises(Exception, match="ConstraintValidationFailed|already exists"):
                s.run("CREATE (:Service {id: 'test-svc-1'})")
            s.run("MATCH (svc:Service {id: 'test-svc-1'}) DETACH DELETE svc")


# ---------------------------------------------------------------------------
# AC-3: OpenSearch cluster + contextiq_documents index
# ---------------------------------------------------------------------------

class TestAC3_OpenSearch:

    @pytest.fixture(scope="class")
    def os_client(self):
        return OpenSearch(
            hosts=[{
                "host": os.environ.get(
                    "OPENSEARCH_HOST",
                    "opensearch.contextiq-data.svc.cluster.local",
                ),
                "port": 9200,
            }],
            http_auth=("admin", os.environ["OPENSEARCH_PASSWORD"]),
            use_ssl=True,
            verify_certs=False,
        )

    def test_opensearch_cluster_green(self, os_client) -> None:
        health = os_client.cluster.health(wait_for_status="green", timeout="30s")
        assert health["number_of_nodes"] == 3
        assert health["status"] == "green"

    def test_contextiq_documents_index_exists(self, os_client) -> None:
        assert os_client.indices.exists(index="contextiq_documents"), (
            "contextiq_documents index not found"
        )

    def test_index_has_required_fields(self, os_client) -> None:
        mapping = os_client.indices.get_mapping(index="contextiq_documents")
        fields = mapping["contextiq_documents"]["mappings"]["properties"]
        for required in ("content", "source_id", "metadata", "indexed_at"):
            assert required in fields, f"Field {required!r} missing from index mapping"

    def test_bm25_similarity(self, os_client) -> None:
        settings = os_client.indices.get_settings(index="contextiq_documents")
        sim = settings["contextiq_documents"]["settings"]["index"].get("similarity", {})
        assert sim.get("default", {}).get("type") == "BM25", "BM25 similarity not configured"


# ---------------------------------------------------------------------------
# AC-4: Redis Sentinel HA + keyspace notifications
# ---------------------------------------------------------------------------

class TestAC4_Redis:

    @pytest.fixture(scope="class")
    def sentinel(self):
        return Sentinel(
            [("redis-headless.contextiq-data.svc.cluster.local", 26379)],
            sentinel_kwargs={"password": os.environ["REDIS_PASSWORD"]},
            password=os.environ["REDIS_PASSWORD"],
            decode_responses=True,
        )

    @pytest.mark.asyncio
    async def test_sentinel_master_discovered(self, sentinel) -> None:
        host, _port = await sentinel.discover_master("contextiq-redis")
        assert host, "Sentinel could not discover Redis master"

    @pytest.mark.asyncio
    async def test_sentinel_has_2_replicas(self, sentinel) -> None:
        slaves = await sentinel.discover_slaves("contextiq-redis")
        assert len(slaves) >= 2, f"Expected 2 replicas, got {len(slaves)}"

    @pytest.mark.asyncio
    async def test_keyspace_notifications_enabled(self, sentinel) -> None:
        master: aioredis.Redis = sentinel.master_for("contextiq-redis")
        config: dict[str, str] = await master.config_get("notify-keyspace-events")
        events = config.get("notify-keyspace-events", "")
        assert "K" in events and "E" in events, (
            f"Keyspace notifications KEA not enabled: {events!r}"
        )
        await master.aclose()


# ---------------------------------------------------------------------------
# AC-5: MinIO distributed + contextiq-traces bucket lifecycle
# ---------------------------------------------------------------------------

class TestAC5_MinIO:

    def test_minio_pods_running(self) -> None:
        result = subprocess.run(
            [
                "kubectl", "get", "pods",
                "-n", "contextiq-infra",
                "-l", "app=minio",
                "-o", "jsonpath={.items[*].status.phase}",
            ],
            capture_output=True,
            timeout=15,
        )
        phases = result.stdout.decode().split()
        assert len(phases) == 4 and all(p == "Running" for p in phases), (
            f"Expected 4 Running MinIO pods, got: {phases}"
        )

    def test_contextiq_traces_bucket_exists(self) -> None:
        result = subprocess.run(
            ["mc", "--json", "stat", "contextiq/contextiq-traces"],
            capture_output=True,
            timeout=15,
        )
        first = result.stdout.decode().strip().split("\n")[0]
        data: dict[str, object] = json.loads(first)
        assert data.get("status") == "success", "contextiq-traces bucket does not exist"

    def test_versioning_enabled_on_traces(self) -> None:
        result = subprocess.run(
            ["mc", "--json", "version", "info", "contextiq/contextiq-traces"],
            capture_output=True,
            timeout=15,
        )
        first = result.stdout.decode().strip().split("\n")[0]
        data: dict[str, object] = json.loads(first)
        assert data.get("status") == "enabled", (
            f"Versioning not enabled on contextiq-traces: {data}"
        )

    def test_lifecycle_rules_present(self) -> None:
        result = subprocess.run(
            ["mc", "--json", "ilm", "ls", "contextiq/contextiq-traces"],
            capture_output=True,
            timeout=15,
        )
        output = result.stdout.decode()
        assert "365" in output or "1y" in output or "expire" in output.lower(), (
            "1-year expiry lifecycle rule not found on contextiq-traces"
        )


# ---------------------------------------------------------------------------
# AC-6: Vault credentials injected into all store pods
# ---------------------------------------------------------------------------

class TestAC6_VaultCredentials:

    @pytest.mark.parametrize("namespace,label,secret_file", [
        ("contextiq-data",  "app.kubernetes.io/name=qdrant", "/vault/secrets/qdrant.env"),
        ("contextiq-data",  "app.kubernetes.io/name=redis",  "/vault/secrets/redis.env"),
        ("contextiq-infra", "app=minio",                     "/vault/secrets/minio.env"),
    ])
    def test_vault_secret_file_present(
        self, namespace: str, label: str, secret_file: str
    ) -> None:
        pod_name = subprocess.run(
            [
                "kubectl", "get", "pods",
                "-n", namespace,
                "-l", label,
                "-o", "jsonpath={.items[0].metadata.name}",
            ],
            capture_output=True,
            timeout=15,
        ).stdout.decode().strip()
        assert pod_name, f"No pod found for {label} in {namespace}"

        result = subprocess.run(
            ["kubectl", "exec", "-n", namespace, pod_name, "--", "test", "-f", secret_file],
            capture_output=True,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"Vault secret file {secret_file} not found in {namespace}/{pod_name}"
        )


# ---------------------------------------------------------------------------
# AC-7: Prometheus ServiceMonitors exist for all stores
# ---------------------------------------------------------------------------

class TestAC7_ServiceMonitors:

    @pytest.mark.parametrize("sm_name", [
        "qdrant", "neo4j", "opensearch", "redis", "minio",
    ])
    def test_servicemonitor_exists(self, sm_name: str) -> None:
        result = subprocess.run(
            [
                "kubectl", "get", "servicemonitor", sm_name,
                "-n", "contextiq-observability",
                "-o", "jsonpath={.metadata.name}",
            ],
            capture_output=True,
            timeout=15,
        )
        assert result.returncode == 0 and result.stdout.decode().strip() == sm_name, (
            f"ServiceMonitor '{sm_name}' not found in contextiq-observability"
        )
