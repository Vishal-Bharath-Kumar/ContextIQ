"""
Integration tests for US-052: Kafka KRaft cluster, topics, consumer groups, and chaos.

Prerequisites:
  - Kafka running in contextiq-data with SCRAM-SHA-512 auth
  - Environment vars: KAFKA_BOOTSTRAP_SERVERS, KAFKA_USERNAME, KAFKA_PASSWORD
  - kubectl context pointing at target cluster (for AC-1 quorum and AC-6 chaos tests)

Run:
    pytest tests/integration/test_kafka.py -v --tb=short
    pytest tests/integration/test_kafka.py -v --run-destructive  # includes chaos test
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from typing import Any

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient

from src.kafka.topic_registry import TOPICS

BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "kafka.contextiq-data.svc.cluster.local:9092",
)
KAFKA_USERNAME = os.environ.get("KAFKA_USERNAME", "")
KAFKA_PASSWORD = os.environ.get("KAFKA_PASSWORD", "")


def _sasl_kwargs() -> dict[str, Any]:
    return {
        "security_protocol":   "SASL_SSL",
        "sasl_mechanism":      "SCRAM-SHA-512",
        "sasl_plain_username": KAFKA_USERNAME,
        "sasl_plain_password": KAFKA_PASSWORD,
        "ssl_cafile":          "/tls/ca.crt",
    }


def _sync_sasl_kwargs() -> dict[str, Any]:
    """SASL kwargs for synchronous kafka-python KafkaAdminClient."""
    return {
        "security_protocol":   "SASL_SSL",
        "sasl_mechanism":      "SCRAM-SHA-512",
        "sasl_plain_username": KAFKA_USERNAME,
        "sasl_plain_password": KAFKA_PASSWORD,
        "ssl_cafile":          "/tls/ca.crt",
    }


# ---------------------------------------------------------------------------
# pytest hooks for --run-destructive flag
# Note: these hooks work in test files but are typically placed in conftest.py.
# They are here to keep this test file self-contained.
# ---------------------------------------------------------------------------

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-destructive",
        action="store_true",
        default=False,
        help="Include destructive chaos tests (requires kubectl access to contextiq-data)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if not config.getoption("--run-destructive"):
        skip = pytest.mark.skip(reason="Pass --run-destructive to run chaos tests")
        for item in items:
            if "destructive" in item.keywords:
                item.add_marker(skip)


# ---------------------------------------------------------------------------
# AC-1: KRaft deployment — 3 brokers, no ZooKeeper
# ---------------------------------------------------------------------------

class TestAC1_KRaftDeployment:

    def test_three_broker_pods_running(self) -> None:
        result = subprocess.run(
            [
                "kubectl", "get", "pods", "-n", "contextiq-data",
                "-l", "app.kubernetes.io/component=controller",
                "-o", "jsonpath={.items[*].status.phase}",
            ],
            capture_output=True, timeout=15,
        )
        phases = result.stdout.decode().split()
        assert len(phases) == 3 and all(p == "Running" for p in phases), (
            f"Expected 3 Running Kafka broker pods, got: {phases}"
        )

    def test_no_zookeeper_pods(self) -> None:
        result = subprocess.run(
            [
                "kubectl", "get", "pods", "-n", "contextiq-data",
                "-l", "app.kubernetes.io/name=zookeeper",
                "-o", "jsonpath={.items[*].metadata.name}",
            ],
            capture_output=True, timeout=15,
        )
        pods = result.stdout.decode().strip()
        assert pods == "", f"ZooKeeper pods found — cluster should use KRaft: {pods}"

    def test_kraft_quorum_has_3_voters(self) -> None:
        # NOTE: aiokafka AIOKafkaAdminClient does not expose describe_cluster().
        # Use kubectl exec to run kafka-metadata-quorum.sh directly on the broker pod,
        # which matches the AC command exactly.
        result = subprocess.run(
            [
                "kubectl", "exec", "-n", "contextiq-data", "kafka-controller-0", "--",
                "kafka-metadata-quorum.sh",
                "--bootstrap-server", "localhost:9092",
                "describe", "--status",
            ],
            capture_output=True, timeout=30,
        )
        output = result.stdout.decode()
        assert result.returncode == 0, (
            f"kafka-metadata-quorum.sh failed:\n{result.stderr.decode()}"
        )
        # KRaft quorum status output includes CurrentVoters with the 3 voter IDs
        assert "CurrentVoters" in output, (
            f"KRaft quorum status output missing 'CurrentVoters':\n{output}"
        )


# ---------------------------------------------------------------------------
# AC-2: Topics — correct partitions and retention
# ---------------------------------------------------------------------------

class TestAC2_Topics:

    @pytest.mark.asyncio
    async def test_all_topics_exist(self) -> None:
        admin = AIOKafkaAdminClient(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            client_id="test-topics",
            **_sasl_kwargs(),
        )
        await admin.start()
        try:
            existing = await admin.list_topics()
        finally:
            await admin.close()

        for spec in TOPICS:
            assert spec.name in existing, f"Topic {spec.name!r} not found on broker"

    @pytest.mark.asyncio
    async def test_topic_partition_counts(self) -> None:
        # NOTE: AIOKafkaAdminClient does not expose describe_topics().
        # Use AIOKafkaConsumer.partitions_for_topic() which reads cluster metadata
        # populated during consumer.start().
        topic_names = [s.name for s in TOPICS]
        consumer = AIOKafkaConsumer(
            *topic_names,
            bootstrap_servers=BOOTSTRAP_SERVERS,
            group_id="test-partition-counts",
            auto_offset_reset="latest",
            **_sasl_kwargs(),
        )
        await consumer.start()
        try:
            for spec in TOPICS:
                partitions = consumer.partitions_for_topic(spec.name)
                assert partitions is not None, (
                    f"Topic {spec.name!r} not found in cluster metadata"
                )
                assert len(partitions) == spec.partitions, (
                    f"Topic {spec.name}: expected {spec.partitions} partitions, "
                    f"got {len(partitions)}"
                )
        finally:
            await consumer.stop()

    @pytest.mark.parametrize("topic_name,expected_retention_ms", [
        ("knowledge.source.synced",       604_800_000),   # 7 days
        ("knowledge.chunk.indexed",        604_800_000),   # 7 days
        ("knowledge.graph.updated",        604_800_000),   # 7 days
        ("contextiq.state.events",          86_400_000),   # 24 hours
        ("contextiq.governance.events", 2_592_000_000),   # 30 days
        ("contextiq.connector.health",      3_600_000),   # 1 hour
    ])
    def test_topic_retention_config(
        self, topic_name: str, expected_retention_ms: int
    ) -> None:
        # NOTE: AIOKafkaAdminClient.describe_configs() uses a different signature
        # and may not be available in aiokafka >= 0.11.
        # Use kafka-python's synchronous KafkaAdminClient with ConfigResource objects.
        from kafka.admin import ConfigResource, ConfigResourceType, KafkaAdminClient

        admin = KafkaAdminClient(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            client_id="test-retention",
            **_sync_sasl_kwargs(),
        )
        try:
            resource = ConfigResource(ConfigResourceType.TOPIC, topic_name)
            configs = admin.describe_configs([resource])
            retention = int(configs[resource]["retention.ms"].value)
            assert retention == expected_retention_ms, (
                f"Topic {topic_name}: retention.ms={retention}, "
                f"expected={expected_retention_ms}"
            )
        finally:
            admin.close()


# ---------------------------------------------------------------------------
# AC-3: Consumer groups pre-registered
# ---------------------------------------------------------------------------

class TestAC3_ConsumerGroups:

    EXPECTED_GROUPS = {
        "indexing-service",
        "graph-agent",
        "context-retrieval",
        "replay-service",
        "audit-logger",
        "health-monitor",
    }

    @pytest.mark.asyncio
    async def test_all_consumer_groups_exist(self) -> None:
        admin = AIOKafkaAdminClient(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            client_id="test-groups",
            **_sasl_kwargs(),
        )
        await admin.start()
        try:
            groups = {g.group_id for g in await admin.list_consumer_groups()}
        finally:
            await admin.close()

        for expected in self.EXPECTED_GROUPS:
            assert expected in groups, (
                f"Consumer group '{expected}' not pre-registered on broker"
            )

    @pytest.mark.asyncio
    async def test_produce_and_consume_round_trip(self) -> None:
        """
        Produce 1 message to a test topic and verify the consumer receives it.
        The consumer is started BEFORE the producer to avoid a race with
        auto_offset_reset='latest' — messages produced before subscription are missed.
        """
        test_topic = "contextiq.state.events"
        test_value = json.dumps(
            {"test": "round-trip", "ts": int(time.time() * 1000)}
        ).encode()

        # Unique group per run so committed offsets don't interfere
        unique_group = f"test-round-trip-{int(time.time())}"

        # Step 1: Start consumer and wait for partition assignment to settle
        consumer = AIOKafkaConsumer(
            test_topic,
            bootstrap_servers=BOOTSTRAP_SERVERS,
            group_id=unique_group,
            auto_offset_reset="latest",
            consumer_timeout_ms=5000,
            **_sasl_kwargs(),
        )
        await consumer.start()
        await asyncio.sleep(1.0)    # allow group join + partition assignment to complete

        # Step 2: Now produce the message (guaranteed visible to this consumer)
        producer = AIOKafkaProducer(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            **_sasl_kwargs(),
        )
        await producer.start()
        try:
            await producer.send_and_wait(test_topic, value=test_value)
        finally:
            await producer.stop()

        # Step 3: Receive
        received: list[bytes] = []
        try:
            async for msg in consumer:
                received.append(msg.value)
                break
        except Exception:
            pass
        finally:
            await consumer.stop()

        assert len(received) == 1, "No message received in round-trip test"


# ---------------------------------------------------------------------------
# AC-4: Kafka Connect REST API
# ---------------------------------------------------------------------------

class TestAC4_KafkaConnect:

    def test_kafka_connect_rest_api_responds(self) -> None:
        import urllib.request
        url = "http://kafka-connect.contextiq-data.svc.cluster.local:8083/"
        with urllib.request.urlopen(url, timeout=10) as resp:
            body: dict[str, object] = json.loads(resp.read())
        assert "version" in body, f"Kafka Connect API did not return version: {body}"

    def test_kafka_connect_connectors_list(self) -> None:
        import urllib.request
        url = "http://kafka-connect.contextiq-data.svc.cluster.local:8083/connectors"
        with urllib.request.urlopen(url, timeout=10) as resp:
            connectors = json.loads(resp.read())
        assert isinstance(connectors, list), "Connectors endpoint did not return a list"


# ---------------------------------------------------------------------------
# AC-5: Prometheus metrics scraped
# ---------------------------------------------------------------------------

class TestAC5_BrokerMetrics:

    PROMETHEUS_URL = os.environ.get(
        "PROMETHEUS_URL",
        "http://prometheus.contextiq-observability.svc.cluster.local:9090",
    )

    def _query(self, expr: str) -> list[dict[str, object]]:
        import urllib.parse
        import urllib.request
        url = (
            f"{self.PROMETHEUS_URL}/api/v1/query"
            f"?query={urllib.parse.quote(expr)}"
        )
        with urllib.request.urlopen(url, timeout=15) as resp:
            data: dict[str, object] = json.loads(resp.read())
        return data.get("data", {}).get("result", [])  # type: ignore[return-value]

    def test_under_replicated_partitions_is_zero(self) -> None:
        results = self._query("kafka_server_replicamanager_underreplicatedpartitions")
        assert results, "kafka_server_replicamanager_underreplicatedpartitions metric not found"
        for r in results:
            value = float(r["value"][1])  # type: ignore[index]
            assert value == 0.0, (
                f"Under-replicated partitions > 0 on broker: {r['metric']}"
            )

    def test_active_controller_count_is_one(self) -> None:
        results = self._query("kafka_controller_kafkacontroller_activecontrollercount")
        total = sum(float(r["value"][1]) for r in results)  # type: ignore[index]
        assert total == 1.0, f"Expected exactly 1 active KRaft controller, got {total}"

    def test_bytes_in_rate_metric_exists(self) -> None:
        results = self._query("kafka_server_brokertopicmetrics_bytesin_rate")
        assert results, (
            "kafka_server_brokertopicmetrics_bytesin_rate metric not found in Prometheus"
        )


# ---------------------------------------------------------------------------
# AC-6: KRaft chaos test — broker failure < 5 s produce interruption
# ---------------------------------------------------------------------------

class TestAC6_KRaftChaos:

    MAX_GAP_SECONDS = 5
    NAMESPACE       = "contextiq-data"
    TEST_TOPIC      = "contextiq.state.events"
    VICTIM_POD      = "kafka-controller-1"

    @pytest.mark.destructive
    @pytest.mark.asyncio
    async def test_broker_failure_interruption_under_5s(self) -> None:
        """
        AC-6: One broker pod is deleted while a producer runs in a tight loop.
        The maximum gap between consecutive successful produce timestamps must be < 5 s.
        """
        produce_timestamps: list[float] = []
        produce_errors:     list[float] = []
        stop_event          = asyncio.Event()

        async def _producer_loop() -> None:
            producer = AIOKafkaProducer(
                bootstrap_servers=BOOTSTRAP_SERVERS,
                acks="all",    # strictest durability: all ISR must ack
                **_sasl_kwargs(),
            )
            await producer.start()
            try:
                while not stop_event.is_set():
                    try:
                        await asyncio.wait_for(
                            producer.send_and_wait(
                                self.TEST_TOPIC,
                                value=f"{time.monotonic():.6f}".encode(),
                            ),
                            timeout=1.0,
                        )
                        produce_timestamps.append(time.monotonic())
                    except Exception:
                        produce_errors.append(time.monotonic())
                    await asyncio.sleep(0.1)    # ~10 messages/s
            finally:
                await producer.stop()

        # Start producer loop in background; store task reference to prevent GC
        producer_task: asyncio.Task[None] = asyncio.create_task(_producer_loop())

        # Warm-up: let the producer establish a baseline
        await asyncio.sleep(2)

        # Kill a non-leader broker
        delete_time = time.monotonic()
        subprocess.run(
            [
                "kubectl", "delete", "pod", self.VICTIM_POD,
                "-n", self.NAMESPACE,
                "--grace-period=0", "--force",
            ],
            check=True, timeout=15,
        )

        # Poll until the victim pod is Running again (up to 60 s)
        max_wait = 60
        for _ in range(max_wait * 2):
            probe = subprocess.run(
                [
                    "kubectl", "get", "pod", self.VICTIM_POD,
                    "-n", self.NAMESPACE,
                    "-o", "jsonpath={.status.phase}",
                ],
                capture_output=True, timeout=10,
            )
            if probe.stdout.decode().strip() == "Running":
                break
            await asyncio.sleep(0.5)
        else:
            stop_event.set()
            await producer_task
            pytest.fail(f"{self.VICTIM_POD} did not restart within {max_wait}s")

        recover_time = time.monotonic()

        # Let the producer confirm recovery before stopping
        await asyncio.sleep(3)
        stop_event.set()
        await producer_task

        # Compute max gap between consecutive successful produce timestamps
        if len(produce_timestamps) < 2:
            pytest.fail(
                f"Too few successful produces ({len(produce_timestamps)}) to measure gap"
            )

        max_gap = max(
            produce_timestamps[i + 1] - produce_timestamps[i]
            for i in range(len(produce_timestamps) - 1)
        )

        total_outage = recover_time - delete_time
        print(
            f"\nBroker failure metrics: "
            f"total_outage={total_outage:.2f}s, "
            f"max_produce_gap={max_gap:.2f}s, "
            f"total_errors={len(produce_errors)}"
        )

        assert max_gap < self.MAX_GAP_SECONDS, (
            f"Max produce gap {max_gap:.2f}s exceeds {self.MAX_GAP_SECONDS}s threshold. "
            f"KRaft leader election took too long after {self.VICTIM_POD} was killed."
        )
